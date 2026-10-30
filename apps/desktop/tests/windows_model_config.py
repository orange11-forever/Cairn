"""Run with the bundle's Windows Python; only uses synthetic keys and a new data directory."""

import argparse
import json
import os
import queue
import subprocess
import threading
import zipfile
from pathlib import Path
from uuid import uuid4

KEY = "cairn-test-synthetic-key-not-a-user-secret"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--work", type=Path, required=True)
    args = parser.parse_args()
    if os.name != "nt":
        raise RuntimeError("This test proves Windows DPAPI and must run on Windows")
    if args.work.exists():
        raise RuntimeError("Choose a new empty test work directory")
    args.work.mkdir(parents=True)
    bundle, data = args.bundle.resolve(), args.work / "data"
    python = bundle / "python/python.exe"

    def command(name, directory=data, *, payload=None, archive=None, success=True):
        arguments = [
            str(python),
            "-X",
            "utf8",
            "-u",
            "-m",
            "cairn_desktop.runtime",
            name,
            "--bundle",
            str(bundle),
            "--data",
            str(directory),
        ]
        if archive is not None:
            arguments += ["--archive", str(archive)]
        result = subprocess.run(
            arguments,
            input=json.dumps(payload, ensure_ascii=False) if payload is not None else "",
            encoding="utf-8",
            capture_output=True,
            timeout=180,
            creationflags=0x08000000,
            check=False,
        )
        if KEY in result.stdout or KEY in result.stderr:
            raise AssertionError("CLI exposed a synthetic credential")
        assert (result.returncode == 0) == success, (
            "CLI status differed; inspect this controlled test directory's runtime.log"
        )
        return result

    def connection(model="本地测试模型", key=KEY, address="http://127.0.0.1:9/v1"):
        return {"protocol": "openai-responses", "baseUrl": address, "model": model, "apiKey": key}

    def payload(embedding=False, key=KEY, address="http://127.0.0.1:9/v1", model="受控索引模型"):
        return {
            "answerModels": [{**connection(key=key), "id": "default", "name": "本地测试模型"}],
            "defaultModelId": "default",
            "embedding": {"baseUrl": address, "model": model, "apiKey": key} if embedding else None,
        }

    assert json.loads(command("model-status").stdout)["indexingPaused"] is True
    original_settings = (data / "settings.json").read_bytes()
    saved = command("model-configure", payload=payload())
    assert json.loads(saved.stdout)["answerModels"][0]["hasKey"] is True
    assert json.loads(saved.stdout)["answerModels"][0]["model"] == "本地测试模型"
    encrypted = data / "model-settings.dpapi"
    assert KEY.encode() not in encrypted.read_bytes()
    from cairn_desktop.models import load_models

    assert load_models(data).answer_models[0].api_key.get_secret_value() == KEY
    command("model-configure", payload=payload(key=""))
    assert load_models(data).answer_models[0].api_key.get_secret_value() == KEY
    before = encrypted.read_bytes()
    invalid = payload()
    invalid["answerModels"][0]["baseUrl"] = "http://127.0.0.1/v1?key=" + KEY
    failed = command("model-configure", payload=invalid, success=False)
    assert "模型配置字段无效" in failed.stderr
    assert encrypted.read_bytes() == before
    from cairn_desktop.data import DataLock

    with DataLock(data):
        command("model-status", success=False)
    encrypted.write_bytes(b"not-a-valid-dpapi-blob")
    assert json.loads(command("model-status").stdout)["corrupt"] is True
    command("model-configure", payload=payload(), success=False)
    command("model-configure", payload={"clearAll": True})
    assert json.loads(command("model-status").stdout)["answerModels"] == []
    assert (data / "settings.json").read_bytes() == original_settings
    command("model-configure", payload=payload(embedding=True))

    active = []
    stderr_chunks = []

    def start(directory):
        arguments = [
            str(python),
            "-X",
            "utf8",
            "-u",
            "-m",
            "cairn_desktop.runtime",
            "serve",
            "--bundle",
            str(bundle),
            "--data",
            str(directory),
        ]
        process = subprocess.Popen(
            arguments,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            encoding="utf-8",
            creationflags=0x08000000,
        )
        active.append(process)
        received = queue.Queue()
        threading.Thread(
            target=lambda: received.put(process.stdout.readline()), daemon=True
        ).start()
        threading.Thread(
            target=lambda: stderr_chunks.append(process.stderr.read()), daemon=True
        ).start()
        line = received.get(timeout=150)
        assert line, "Supervisor did not report readiness"
        ready = json.loads(line)
        return process, ready

    def stop(process):
        process.stdin.write("stop\n")
        process.stdin.flush()
        process.stdin.close()
        process.wait(timeout=100)
        assert process.returncode == 0
        active.remove(process)

    try:
        process, ready = start(data)
        assert ready["modelStatus"]["answerModels"][0]["model"] == "本地测试模型"
        assert ready["modelStatus"]["indexingPaused"] is False
        import psycopg

        password = json.loads(original_settings)["databasePassword"]

        def connect(ready):
            return psycopg.connect(
                host="127.0.0.1",
                port=ready["postgresPort"],
                dbname="cairn",
                user="cairn",
                password=password,
                autocommit=True,
            )

        org, project, resource, version = (uuid4() for _ in range(4))
        with connect(ready) as db:
            identity = db.execute("SELECT provider_key,model FROM embedding_profiles").fetchone()
            assert identity[1] == "受控索引模型" and len(identity[0]) == 64
            db.execute(
                "INSERT INTO organizations(id,slug,name) VALUES(%s,%s,'Desktop model proof')",
                (org, "proof-" + org.hex[:12]),
            )
            db.execute(
                "INSERT INTO projects(id,org_id,name) VALUES(%s,%s,'Retained project')",
                (project, org),
            )
            db.execute(
                "INSERT INTO knowledge_resources(id,org_id,project_id,title,source_type,source_id,external_id) VALUES(%s,%s,%s,'retained.txt','upload','proof','retained.txt')",
                (resource, org, project),
            )
            db.execute(
                "INSERT INTO knowledge_resource_versions(id,org_id,project_id,resource_id,source_type,source_id,external_id,source_version,object_key,media_type,size_bytes,sha256,parser_profile,chunking_profile,status,processing_started_at,ready_at) VALUES(%s,%s,%s,%s,'upload','proof','retained.txt','1','proof-body','text/plain',1,%s,'default-v1','default-v1','ready',now(),now())",
                (version, org, project, resource, "a" * 64),
            )
            db.execute(
                "UPDATE knowledge_resources SET current_version_id=%s WHERE id=%s",
                (version, resource),
            )
        stop(process)
        before = encrypted.read_bytes()
        command(
            "model-configure",
            payload=payload(embedding=True, address="http://127.0.0.1:8/v1"),
            success=False,
        )
        assert encrypted.read_bytes() == before
        command(
            "model-configure",
            payload=payload(embedding=True, model="different-model"),
            success=False,
        )
        assert encrypted.read_bytes() == before
        command("model-configure", payload=payload(embedding=True, key=KEY + "-rotated"))
        archive = args.work / "proof.cairn"
        command("backup", archive=archive)
        with zipfile.ZipFile(archive) as stored:
            assert "model-settings.dpapi" not in stored.namelist()
        restored = args.work / "restored"
        command("restore", directory=restored, archive=archive)
        assert (
            json.loads(command("model-status", directory=restored).stdout)["indexingPaused"] is True
        )
        process, ready = start(restored)
        assert (
            ready["modelStatus"]["indexingPaused"] is True
            and ready["modelStatus"]["answerModels"] == []
        )
        with connect(ready) as db:
            assert (
                db.execute("SELECT provider_key,model FROM embedding_profiles").fetchone()
                == identity
            )
            assert (
                db.execute("SELECT count(*) FROM projects WHERE id=%s", (project,)).fetchone()[0]
                == 1
            )
            index_job = uuid4()
            db.execute(
                "INSERT INTO ingestion_jobs(id,org_id,project_id,job_kind,target_id,profile_version) VALUES(%s,%s,%s,'index_resource_version',%s,'default-v1')",
                (index_job, org, project, version),
            )
            import time

            time.sleep(1.5)
            assert db.execute(
                "SELECT status,last_error_code FROM ingestion_jobs WHERE id=%s", (index_job,)
            ).fetchone() == ("queued", None)
            assert (
                db.execute(
                    "SELECT count(*) FROM ingestion_job_attempts WHERE job_id=%s", (index_job,)
                ).fetchone()[0]
                == 0
            )
        stop(process)
        if (
            KEY in "".join(stderr_chunks)
            or KEY.encode("utf-8") in (data / "logs/runtime.log").read_bytes()
        ):
            raise AssertionError("Runtime exposed a synthetic credential")
        print(
            json.dumps(
                {
                    "status": "PASS",
                    "checks": [
                        "real-user-DPAPI",
                        "utf8-cli-and-diagnostics",
                        "masked-metadata",
                        "blank-key-retention",
                        "corruption-clear-recovery",
                        "data-lock",
                        "pre-save-binding-refusal",
                        "same-identity-key-rotation",
                        "backup-excludes-credentials",
                        "restore-preserves-index-profile",
                        "missing-credentials-pauses-claim",
                    ],
                }
            )
        )
    finally:
        for process in active:
            process.kill()
            process.wait(timeout=15)


if __name__ == "__main__":
    main()
