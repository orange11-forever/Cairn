"""Windows desktop supervisor: one private database, API and ingestion worker."""

import argparse
import json
import logging
import os
import secrets
import socket
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path

from cairn_desktop.data import DataLock, backup_data, restore_data, validate_data_directory

logger = logging.getLogger(__name__)


def run_command(arguments, log, *, timeout=90):
    result = subprocess.run(
        [str(value) for value in arguments],
        stdout=log,
        stderr=log,
        stdin=subprocess.DEVNULL,
        timeout=timeout,
        creationflags=0x08000000,
        check=False,
    )
    if result.returncode:
        raise RuntimeError(
            f"{Path(arguments[0]).name} failed ({result.returncode}); see runtime.log"
        )


def protect_directory(directory: Path):
    directory.mkdir(parents=True, exist_ok=True)
    # Limit this app-owned directory to its current user, SYSTEM and administrators.
    import csv

    identity = subprocess.check_output(
        ["whoami", "/user", "/fo", "csv", "/nh"], creationflags=0x08000000, text=True
    )
    sid = next(csv.reader([identity.strip()]))[1]
    subprocess.run(
        [
            "icacls",
            str(directory),
            "/inheritance:r",
            "/grant:r",
            f"*{sid}:(OI)(CI)F",
            "*S-1-5-18:(OI)(CI)F",
            "*S-1-5-32-544:(OI)(CI)F",
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        creationflags=0x08000000,
    )


def load_settings(directory: Path):
    path = directory / "settings.json"
    if not path.exists():
        if (directory / "postgres" / "PG_VERSION").exists():
            raise RuntimeError("Existing database has no settings.json; restore a complete backup")
        values = {
            "version": 1,
            **{
                name: secrets.token_hex(32)
                for name in (
                    "databasePassword",
                    "csrfSecret",
                    "rateLimitSecret",
                    "searchSecret",
                    "objectSecret",
                )
            },
        }
        with path.open("x", encoding="utf-8") as output:
            json.dump(values, output)
            output.flush()
            os.fsync(output.fileno())
    values = json.loads(path.read_text(encoding="utf-8"))
    if (
        not isinstance(values, dict)
        or values.get("version") != 1
        or any(
            not isinstance(values.get(key), str)
            or len(values[key]) != 64
            or any(c not in "0123456789abcdef" for c in values[key])
            for key in (
                "databasePassword",
                "csrfSecret",
                "rateLimitSecret",
                "searchSecret",
                "objectSecret",
            )
        )
    ):
        raise RuntimeError("Invalid desktop settings.json; no data has been reset")
    return values


def reserve_port():
    handle = socket.socket()
    handle.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
    handle.bind(("127.0.0.1", 0))
    return handle


def initialize_database(bundle: Path, data: Path, values: dict, log):
    cluster = data / "postgres"
    if (cluster / "PG_VERSION").exists():
        if (cluster / "PG_VERSION").read_text().strip() != "18":
            raise RuntimeError("Database major version differs from this PostgreSQL 18 bundle")
        return
    if cluster.exists():
        raise RuntimeError("Incomplete database directory; move it aside or restore a backup")
    password_file = data / ".initdb-password"
    try:
        password_file.write_text(values["databasePassword"], encoding="utf-8")
        run_command(
            [
                bundle / "postgres/bin/initdb.exe",
                "-D",
                cluster,
                "--username=cairn",
                "--auth=scram-sha-256",
                "--encoding=UTF8",
                "--no-locale",
                f"--pwfile={password_file}",
            ],
            log,
        )
    finally:
        password_file.unlink(missing_ok=True)


def prepare_database(bundle: Path, values: dict, pg_port: int):
    import psycopg
    from alembic import command
    from alembic.config import Config

    password = values["databasePassword"]
    with psycopg.connect(
        host="127.0.0.1",
        port=pg_port,
        user="cairn",
        password=password,
        dbname="postgres",
        autocommit=True,
    ) as connection:
        if not connection.execute("SELECT 1 FROM pg_database WHERE datname = 'cairn'").fetchone():
            connection.execute("CREATE DATABASE cairn")
    url = f"postgresql+psycopg://cairn:{password}@127.0.0.1:{pg_port}/cairn"
    migrations = Config()
    migrations.set_main_option("script_location", str(bundle / "migrations"))
    migrations.set_main_option("sqlalchemy.url", url)
    command.upgrade(migrations, "head")
    return url


def build_desktop_settings(values, origin, url, models, provider_key, embedding_model):
    from cairn_api.settings import Settings

    class DesktopSettings(Settings):
        @classmethod
        def settings_customise_sources(
            cls, settings_cls, init_settings, env_settings, dotenv_settings, file_secret_settings
        ):
            return (init_settings,)

    answer, embedding = models.answer, models.embedding
    return DesktopSettings(
        _env_file=None,
        database_url=url,
        app_url=origin,
        cors_origins=[origin],
        csrf_secret=values["csrfSecret"],
        auth_rate_limit_secret=values["rateLimitSecret"],
        search_audit_secret=values["searchSecret"],
        answer_base_url=answer.base_url if answer else None,
        answer_model=answer.model if answer else None,
        answer_api_key=answer.api_key if answer else None,
        answer_protocol=answer.protocol if answer else "openai-compatible",
        answer_models=[],
        embedding_base_url=embedding.base_url if embedding else "http://127.0.0.1:9/v1",
        embedding_model=embedding_model,
        embedding_provider_key=provider_key,
        embedding_api_key=embedding.api_key if embedding else "desktop-indexing-paused",
        embedding_dimensions=1024,
    )


class PausedEmbeddingClient:
    dimensions = 1024

    def __init__(self, provider_key, model):
        self.provider_key, self.model = provider_key, model

    def embed_query(self, _query):
        from cairn_api.knowledge.search_service import EmbeddingUnavailable

        raise EmbeddingUnavailable()


def build_desktop_handlers(store, session_factory, settings):
    from cairn_api.knowledge.models import JobKind
    from cairn_worker.feishu_credentials import FeishuCredentialResolver
    from cairn_worker.feishu_sync import build_feishu_sync_handler
    from cairn_worker.runner import build_runtime_handlers

    handlers = build_runtime_handlers(
        object_store=store, session_factory=session_factory, settings=settings
    )
    # The desktop has no source-credential settings. Never inherit server-only
    # environment credentials when a restored source job is encountered.
    handlers[JobKind.SYNC_FEISHU_SOURCE] = build_feishu_sync_handler(
        object_store=store, resolver=FeishuCredentialResolver.from_environment({})
    )
    return handlers


def prepare_app(bundle: Path, data: Path, values: dict, origin: str, pg_port: int):
    from cairn_api.app import create_app
    from cairn_api.db.session import Database
    from cairn_worker.runner import WorkerRuntime
    from fastapi import HTTPException
    from starlette.responses import FileResponse

    from cairn_desktop.embedding_binding import bind_embedding_profile
    from cairn_desktop.http import DesktopAccess
    from cairn_desktop.models import load_models, public_status
    from cairn_desktop.object_store import LocalObjectStore

    url = prepare_database(bundle, values, pg_port)
    models = load_models(data)
    database = Database(url)
    try:
        with database.session_factory.begin() as session:
            profile = bind_embedding_profile(session, models.embedding)
            provider_key, embedding_model = profile.provider_key, profile.model
    except Exception:
        database.dispose()
        raise
    settings = build_desktop_settings(values, origin, url, models, provider_key, embedding_model)
    store = LocalObjectStore(data / "objects", origin, bytes.fromhex(values["objectSecret"]))
    app = create_app(
        settings=settings,
        database=database,
        object_store=store,
        embedding_client=None
        if models.embedding
        else PausedEmbeddingClient(provider_key, embedding_model),
    )
    app.state.desktop_model_status = public_status(models)
    app.include_router(store.router())
    worker_database = Database(url)
    worker = WorkerRuntime(
        settings=settings,
        database=worker_database,
        object_store=store,
        handlers=build_desktop_handlers(store, worker_database.session_factory, settings),
        worker_id=f"desktop:{os.getpid()}",
        indexing_enabled=models.embedding is not None,
    )
    web = (bundle / "web").resolve()

    @app.get("/{path:path}", include_in_schema=False)
    def frontend(path: str):
        target = (web / path).resolve()
        if not target.is_relative_to(web) or path.startswith(("api/", "desktop/")):
            raise HTTPException(404)
        if not target.is_file():
            if Path(path).suffix:
                raise HTTPException(404)
            target = web / "index.html"
        return FileResponse(target, headers={"Cache-Control": "no-store"})

    token = secrets.token_hex(32)
    app.add_middleware(DesktopAccess, origin=origin, token=token)
    return app, worker, token


@contextmanager
def running_database(bundle: Path, data: Path, values, log):
    import psycopg

    initialize_database(bundle, data, values, log)
    cluster = data / "postgres"
    with reserve_port() as port_socket:
        pg_port = port_socket.getsockname()[1]
    postgres = None
    try:
        postgres = subprocess.Popen(
            [
                str(bundle / "postgres/bin/postgres.exe"),
                "-D",
                str(cluster),
                "-h",
                "127.0.0.1",
                "-p",
                str(pg_port),
                "-c",
                "unix_socket_directories=",
            ],
            stdout=log,
            stderr=log,
            stdin=subprocess.DEVNULL,
            creationflags=0x08000000,
        )
        deadline = time.monotonic() + 45
        while True:
            if postgres.poll() is not None:
                raise RuntimeError("Bundled PostgreSQL exited during startup; see runtime.log")
            try:
                with psycopg.connect(
                    host="127.0.0.1",
                    port=pg_port,
                    user="cairn",
                    password=values["databasePassword"],
                    dbname="postgres",
                    connect_timeout=2,
                ):
                    break
            except psycopg.OperationalError:
                if time.monotonic() >= deadline:
                    raise RuntimeError(
                        "Bundled PostgreSQL did not become ready; see runtime.log"
                    ) from None
                time.sleep(0.1)
        yield pg_port, postgres
    finally:
        if postgres is not None and postgres.poll() is None:
            run_command(
                [
                    bundle / "postgres/bin/pg_ctl.exe",
                    "-D",
                    cluster,
                    "stop",
                    "-m",
                    "fast",
                    "-w",
                    "-t",
                    "30",
                ],
                log,
                timeout=35,
            )
            postgres.wait(timeout=5)


def serve(bundle: Path, data: Path, log):
    values = load_settings(data)
    with running_database(bundle, data, values, log) as (pg_port, postgres):
        _serve_app(bundle, data, values, log, pg_port, postgres)


def check_model_binding(bundle, data, models, log):
    from cairn_api.db.session import Database

    from cairn_desktop.embedding_binding import bind_embedding_profile

    values = load_settings(data)
    with running_database(bundle, data, values, log) as (pg_port, _postgres):
        url = prepare_database(bundle, values, pg_port)
        database = Database(url)
        try:
            with database.session_factory.begin() as session:
                bind_embedding_profile(session, models.embedding, apply=False)
        finally:
            database.dispose()


def configure_model_settings(bundle, data, payload, log):
    from cairn_desktop.models import prepare_model_update, public_status, save_models

    candidate = prepare_model_update(data, payload)
    if candidate.embedding is not None:
        check_model_binding(bundle, data, candidate, log)
    save_models(data, candidate)
    return public_status(candidate)


def _serve_app(bundle: Path, data: Path, values, log, pg_port, postgres):
    import uvicorn

    api_socket = reserve_port()
    api_socket.listen(128)
    origin = f"http://127.0.0.1:{api_socket.getsockname()[1]}"
    worker = None
    api_thread = None
    worker_thread = None
    stop = threading.Event()
    failures = []
    server = None
    try:
        app, worker, token = prepare_app(bundle, data, values, origin, pg_port)
        server = uvicorn.Server(
            uvicorn.Config(
                app,
                access_log=False,
                log_level="warning",
                proxy_headers=False,
                timeout_graceful_shutdown=35,
            )
        )

        def run_api():
            try:
                server.run(sockets=[api_socket])
            except (Exception, SystemExit) as error:
                logger.exception("Desktop API stopped")
                failures.append(error)
                stop.set()

        def run_worker():
            try:
                while not stop.is_set():
                    if not worker.run_once():
                        stop.wait(0.5)
            except Exception as error:
                logger.exception("Desktop worker stopped")
                failures.append(error)
                stop.set()

        api_thread = threading.Thread(target=run_api, name="cairn-api", daemon=True)
        api_thread.start()
        deadline = time.monotonic() + 30
        while not server.started:
            if not api_thread.is_alive() or time.monotonic() > deadline:
                raise RuntimeError("Desktop API did not become ready")
            time.sleep(0.05)
        worker_thread = threading.Thread(target=run_worker, name="cairn-worker", daemon=True)
        worker_thread.start()
        print(
            json.dumps(
                {
                    "origin": origin,
                    "token": token,
                    "cookie": f"cairn_desktop_{api_socket.getsockname()[1]}",
                    "pid": os.getpid(),
                    "postgresPid": postgres.pid,
                    "postgresPort": pg_port,
                    "modelStatus": app.state.desktop_model_status,
                }
            ),
            flush=True,
        )

        def read_commands():
            # EOF means the native shell disappeared, so never leave services running.
            sys.stdin.readline()
            stop.set()

        threading.Thread(target=read_commands, daemon=True).start()
        while not stop.wait(0.25):
            if (
                postgres.poll() is not None
                or not api_thread.is_alive()
                or not worker_thread.is_alive()
            ):
                raise RuntimeError("A desktop service exited unexpectedly; see runtime.log")
        if failures:
            raise RuntimeError("A desktop service failed; see runtime.log") from failures[0]
    finally:
        stop.set()
        if server is not None:
            server.should_exit = True
        for thread in (worker_thread, api_thread):
            if thread is not None:
                thread.join(timeout=40)
                if thread.is_alive():
                    raise RuntimeError(
                        "Desktop service shutdown timed out; restart will recover the database"
                    )
        if worker is not None:
            worker.close()
        api_socket.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "command", choices=["serve", "backup", "restore", "model-status", "model-configure"]
    )
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--archive", type=Path)
    args = parser.parse_args()
    if sys.platform != "win32":
        parser.error("The current desktop feasibility bundle supports Windows only")
    from cairn_desktop.windows import contain_process_tree

    job = contain_process_tree()
    assert job
    if args.command == "restore":
        if args.archive is None:
            parser.error("restore requires --archive")
        restore_data(args.archive, args.data)
        protect_directory(args.data)
        print("Restored to " + str(args.data))
        return
    validate_data_directory(args.data)
    protect_directory(args.data)
    from cairn_desktop.models import ModelSettingsError

    with DataLock(args.data):
        (args.data / "logs").mkdir(exist_ok=True)
        with (args.data / "logs/runtime.log").open("a", encoding="utf-8", buffering=1) as log:
            logging.basicConfig(stream=log, level=logging.INFO)
            try:
                if args.command == "model-status":
                    from cairn_desktop.models import model_status

                    load_settings(args.data)
                    print(json.dumps(model_status(args.data)), flush=True)
                elif args.command == "model-configure":
                    load_settings(args.data)
                    raw = sys.stdin.buffer.read(32_769)
                    if len(raw) > 32_768:
                        raise ModelSettingsError("模型配置输入过大。")
                    try:
                        payload = json.loads(raw)
                    except (ValueError, UnicodeError):
                        raise ModelSettingsError("模型配置不是有效JSON。") from None
                    print(
                        json.dumps(configure_model_settings(args.bundle, args.data, payload, log)),
                        flush=True,
                    )
                elif args.command == "backup":
                    if args.archive is None:
                        parser.error("backup requires --archive")
                    control = subprocess.check_output(
                        [
                            str(args.bundle / "postgres/bin/pg_controldata.exe"),
                            str(args.data / "postgres"),
                        ],
                        creationflags=0x08000000,
                        env={**os.environ, "LC_MESSAGES": "C", "LANG": "C"},
                        text=True,
                    )
                    if not any(
                        line.startswith("Database cluster state:")
                        and line.split(":", 1)[1].strip() == "shut down"
                        for line in control.splitlines()
                    ):
                        raise RuntimeError(
                            "Database must shut down cleanly before backup; start and close Cairn first"
                        )
                    backup_data(args.data, args.archive)
                    print("Backup saved to " + str(args.archive))
                else:
                    serve(args.bundle, args.data, log)
            except ModelSettingsError as error:
                logger.exception("Desktop model settings failed")
                print(
                    f"{error}\n详细日志：{args.data / 'logs/runtime.log'}",
                    file=sys.stderr,
                    flush=True,
                )
                return 1
            except Exception:
                logger.exception("Desktop runtime failed")
                raise


if __name__ == "__main__":
    raise SystemExit(main())
