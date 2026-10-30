"""Run with the bundled Windows Python. Creates only new test data directories."""

import argparse
import concurrent.futures
import hashlib
import io
import json
import secrets
import socket
import subprocess
import sys
import time
import zipfile
from datetime import timedelta
from pathlib import Path

import httpx
import psycopg
from cairn_desktop.object_store import LocalObjectStore


class Runtime:
    def __init__(self, bundle, data, evidence, *, python=None):
        self.bundle, self.data, self.evidence = bundle, data, evidence
        self.python = python or sys.executable
        self.process = None

    def start(self):
        self.log = (self.evidence / (self.data.name + "-stderr.log")).open("a", encoding="utf-8")
        self.process = subprocess.Popen(
            [
                str(self.python),
                "-u",
                "-m",
                "cairn_desktop.runtime",
                "serve",
                "--bundle",
                str(self.bundle),
                "--data",
                str(self.data),
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=self.log,
            text=True,
            creationflags=0x08000000,
            cwd=self.bundle,
        )
        with concurrent.futures.ThreadPoolExecutor() as pool:
            line = pool.submit(self.process.stdout.readline).result(timeout=120)
        assert line, "runtime exited before ready: " + str(self.evidence)
        self.ready = json.loads(line)
        self.client = httpx.Client(
            base_url=self.ready["origin"],
            trust_env=False,
            timeout=15,
            headers={"X-Cairn-Desktop": self.ready["token"], "Origin": self.ready["origin"]},
        )
        assert self.client.get("/ready").status_code == 200
        return self

    def stop(self, crash=False):
        self.client.close()
        if crash:
            self.process.kill()
        else:
            self.process.stdin.write("stop\n")
            self.process.stdin.flush()
        code = self.process.wait(timeout=90)
        if not crash:
            assert code == 0, "unclean shutdown, see " + str(self.evidence)
        self.log.close()
        for port in (self.ready["postgresPort"], int(self.ready["origin"].rsplit(":", 1)[1])):
            deadline = time.monotonic() + 10
            while True:
                with socket.socket() as probe:
                    closed = probe.connect_ex(("127.0.0.1", port)) != 0
                if closed:
                    break
                assert time.monotonic() < deadline, "orphaned local service"
                time.sleep(0.1)


def data_command(bundle, command, data, archive, *, success=True):
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "cairn_desktop.runtime",
            command,
            "--bundle",
            str(bundle),
            "--data",
            str(data),
            "--archive",
            str(archive),
        ],
        capture_output=True,
        text=True,
        creationflags=0x08000000,
        timeout=180,
        check=False,
    )
    assert (result.returncode == 0) == success, result.stderr[-2500:]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--work", type=Path, required=True)
    args = parser.parse_args()
    work = args.work
    work.mkdir(parents=True, exist_ok=False)
    data = work / "data 中文 space"
    evidence = work / "evidence"
    evidence.mkdir()
    checks = []

    def passed(name):
        checks.append(name)
        (evidence / "checks.json").write_text(json.dumps(checks, indent=2), encoding="utf-8")
        print("PASS " + name, flush=True)

    occupied = []
    for port in (5432, 8080, 5500):
        handle = socket.socket()
        try:
            handle.bind(("127.0.0.1", port))
            handle.listen()
            occupied.append(handle)
        except OSError:
            handle.close()  # Another existing service already occupies this port.
    runtime = Runtime(args.bundle, data, evidence).start()
    try:
        assert runtime.ready["postgresPort"] not in (5432, 8080, 5500)
        passed("first start, automatic migration, existing default ports left untouched")
        origin = runtime.ready["origin"]
        with httpx.Client(trust_env=False) as stranger:
            assert stranger.get(origin + "/ready").status_code == 403
            assert stranger.get(origin + "/api/v1/projects").status_code == 403
        assert runtime.client.get("/ready", headers={"Host": "attacker.test"}).status_code == 403
        assert (
            runtime.client.get("/ready", headers={"Origin": "https://attacker.test"}).status_code
            == 403
        )
        passed("loopback capability, Host and Origin boundaries")
        data_command(args.bundle, "backup", data, work / "live.cairn", success=False)
        passed("running data directory refuses concurrent backup")
        email = "desktop-proof@example.com"
        password = secrets.token_urlsafe(24)

        def login(instance):
            response = instance.client.post(
                "/api/v1/login", json={"email": email, "password": password}
            )
            assert response.status_code == 200, response.text
            instance.client.headers["X-CSRF-Token"] = response.json()["csrfToken"]

        response = runtime.client.post(
            "/api/v1/auth/register",
            json={"email": email, "password": password, "displayName": "桌面验收"},
        )
        assert response.status_code == 201, response.text
        login(runtime)
        response = runtime.client.post("/api/v1/projects", json={"name": "桌面持久化验收"})
        assert response.status_code == 201, response.text
        project = response.json()["id"]
        response = runtime.client.post(
            f"/api/v1/projects/{project}/tasks",
            json={"title": "重启和恢复后保留任务", "description": "native desktop proof"},
        )
        assert response.status_code == 201, response.text
        task = response.json()["id"]
        content = "本地文件字节在退出、崩溃、恢复后保持不变。".encode()
        zipped = io.BytesIO()
        with zipfile.ZipFile(zipped, "w") as archive:
            archive.writestr("desktop-proof.txt", content)
        archive_bytes = zipped.getvalue()
        response = runtime.client.post(
            f"/api/v1/projects/{project}/knowledge/uploads",
            json={
                "files": [
                    {
                        "fileName": "proof.zip",
                        "mediaType": "application/zip",
                        "sizeBytes": len(archive_bytes),
                        "sha256": hashlib.sha256(archive_bytes).hexdigest(),
                    }
                ]
            },
        )
        assert response.status_code == 201, response.text
        instruction = response.json()["uploads"][0]
        response = runtime.client.put(
            instruction["url"], headers=instruction["headers"], content=archive_bytes
        )
        assert response.status_code == 200, response.text
        response = runtime.client.post(
            f"/api/v1/projects/{project}/knowledge/uploads/{instruction['uploadId']}/complete"
        )
        assert response.status_code == 200, response.text
        values = json.loads((data / "settings.json").read_text())
        deadline = time.monotonic() + 30
        while True:
            with psycopg.connect(
                host="127.0.0.1",
                port=runtime.ready["postgresPort"],
                user="cairn",
                password=values["databasePassword"],
                dbname="cairn",
            ) as db:
                jobs = db.execute(
                    "SELECT job_kind, status FROM ingestion_jobs ORDER BY created_at"
                ).fetchall()
                resources = db.execute(
                    "SELECT r.id, v.object_key FROM knowledge_resources r "
                    "JOIN knowledge_resource_versions v ON v.resource_id = r.id "
                    "WHERE r.title = 'desktop-proof.txt'"
                ).fetchall()
            if resources:
                break
            assert time.monotonic() < deadline, repr(jobs)
            time.sleep(0.2)
        resource = str(resources[0][0])
        object_key = resources[0][1]
        passed(
            "register without SMTP, create project/task, upload ZIP, background archive extraction"
        )

        def verify(instance):
            login(instance)
            response = instance.client.get(f"/api/v1/tasks/{task}")
            assert response.status_code == 200, response.text
            assert response.json()["title"] == "重启和恢复后保留任务"
            response = instance.client.get(
                f"/api/v1/projects/{project}/knowledge/resources/{resource}"
            )
            assert response.status_code == 200, response.text
            assert response.json()["latestVersion"]["sha256"] == hashlib.sha256(content).hexdigest()
            # No AI model is configured: the public download endpoint only publishes
            # indexed versions. Verify the real signed local file transport separately.
            stored = json.loads((instance.data / "settings.json").read_text())
            store = LocalObjectStore(
                instance.data / "objects",
                instance.ready["origin"],
                bytes.fromhex(stored["objectSecret"]),
            )
            url = store.presign_get(
                object_key=object_key,
                download_name="desktop-proof.txt",
                expires_in=timedelta(minutes=1),
            )
            response = instance.client.get(url)
            assert response.status_code == 200, response.text
            assert response.content == content

        verify(runtime)
        runtime.stop()
        passed("graceful shutdown closes both listeners")
        old_token = runtime.ready["token"]
        runtime = Runtime(args.bundle, data, evidence).start()
        assert runtime.ready["token"] != old_token
        verify(runtime)
        passed("restart retains account, project, task and exact attachment bytes")
        runtime.stop(crash=True)
        passed("forced supervisor termination kills database children")
        runtime = Runtime(args.bundle, data, evidence).start()
        verify(runtime)
        passed("PostgreSQL crash recovery and lock recovery retain committed data")
        runtime.stop()
        archive = work / "backup.cairn"
        data_command(args.bundle, "backup", data, archive)
        restored = work / "restored 中文 space"
        data_command(args.bundle, "restore", restored, archive)
        data_command(args.bundle, "restore", restored, archive, success=False)
        runtime = Runtime(args.bundle, restored, evidence).start()
        verify(runtime)
        passed(
            "cold backup restores database and attachment into new directory; existing data protected"
        )
        runtime.stop()
        (evidence / "result.json").write_text(
            json.dumps(
                {
                    "passed": len(checks),
                    "project": project,
                    "task": task,
                    "resource": resource,
                    "data": str(data),
                    "restored": str(restored),
                },
                indent=2,
            )
        )
    finally:
        if runtime.process.poll() is None:
            runtime.stop()
        for handle in occupied:
            handle.close()


if __name__ == "__main__":
    main()
