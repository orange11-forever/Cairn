"""Verify the released v0.1.0 installer upgrading to a local 0.1.1 candidate.

Run with a separate current bundled Windows Python. Creates only a new --work.
Knowledge/index fixtures test retention, not ingestion or live model quality.
"""

import argparse
import hashlib
import io
import json
import os
import runpy
import secrets
import subprocess
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
from cairn_desktop.models import unprotect_bytes
from cairn_desktop.object_store import LocalObjectStore
from psycopg.types.json import Jsonb

RELEASE_SHA256 = "1d601b86fffa6be65dd2ac195228d062ecd35c43ef9c32099dad7b6393a133e8"
MANIFEST_SHA256 = "0f336271800677cf279edeca7d50615b2df681c421dfd2d1652a3617b1a4ac9c"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("baseline", "baseline-manifest", "installer", "manifest", "work"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    assert hashlib.sha256(args.baseline.read_bytes()).hexdigest() == RELEASE_SHA256
    assert hashlib.sha256(args.baseline_manifest.read_bytes()).hexdigest() == MANIFEST_SHA256
    helpers = runpy.run_path(str(Path(__file__).with_name("windows_installer.py")))
    registration, setup, tree_hash = (helpers[name] for name in ("registration", "setup", "tree_hash"))
    assert registration() is None, "Existing installation must not be touched"
    assert not helpers["running_signal"](), "Close the native Cairn preview before installer acceptance"
    shortcut = Path(os.environ["APPDATA"]) / "Microsoft/Windows/Start Menu/Programs/Cairn.lnk"
    assert not shortcut.exists(), "Existing shortcut must not be touched"
    args.work.mkdir(parents=True, exist_ok=False)
    work = args.work.resolve()
    evidence = work / "evidence"
    evidence.mkdir()
    destination, data = work / "program with spaces", work / "data 中文"
    default_data = Path(os.environ["LOCALAPPDATA"]) / "Cairn/DesktopPrototype"
    default_before = tree_hash(default_data)
    Runtime = runpy.run_path(str(Path(__file__).with_name("windows_smoke.py")))["Runtime"]
    runtime = None
    checks = []

    def passed(label):
        checks.append(label)
        (evidence / "checks.json").write_text(json.dumps(checks, indent=2), encoding="utf-8")
        print("PASS " + label, flush=True)

    def required(response, status=200):
        assert response.status_code == status, (response.request.url.path, response.status_code, response.text)
        return response.json()

    def verify_payload(manifest_path):
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for name, digest in manifest["sha256"].items():
            assert hashlib.sha256((destination / name).read_bytes()).hexdigest() == digest, name

    def start():
        nonlocal runtime
        runtime = Runtime(destination, data, evidence, python=destination / "python/python.exe")
        runtime.start()

    def stop():
        nonlocal runtime
        runtime.stop()
        runtime = None

    def configure_models(payload):
        result = subprocess.run(
            [str(destination / "python/python.exe"), "-X", "utf8", "-m", "cairn_desktop.runtime",
             "model-configure", "--bundle", str(destination), "--data", str(data)],
            input=json.dumps(payload), text=True, encoding="utf-8", capture_output=True,
            timeout=180, cwd=destination, check=False,
        )
        assert result.returncode == 0, result.stderr

    try:
        setup(args.baseline, destination)
        assert registration() == {"InstallLocation": str(destination), "DisplayVersion": "0.1.0"}
        verify_payload(args.baseline_manifest)
        passed("installed original released v0.1.0 bytes, including its original runtime and migrations")

        start()
        email, password = "historical-upgrade@example.com", secrets.token_urlsafe(24)
        required(runtime.client.post("/api/v1/auth/register", json={
            "email": email, "password": password, "displayName": "历史版本迁移验收",
        }), 201)

        def login():
            assert runtime.client.post("/api/v1/auth/login-context").status_code == 204
            identity = required(runtime.client.post("/api/v1/login", json={"email": email, "password": password}))
            runtime.client.headers["X-CSRF-Token"] = identity["csrfToken"]
            return identity

        identity = login()
        project = required(runtime.client.post("/api/v1/projects", json={"name": "历史版本项目"}), 201)["id"]
        task = required(runtime.client.post(f"/api/v1/projects/{project}/tasks", json={
            "title": "升级后保留旧任务", "remainingEffortMinutes": 90,
        }), 201)
        current_assistant = required(runtime.client.get(f"/api/v1/projects/{project}/knowledge/assistant-settings"))
        assistant = required(runtime.client.post(f"/api/v1/projects/{project}/knowledge/assistants", json={
            "expectedRevision": current_assistant["revision"], "name": "历史助手", "instructions": "保留旧版行为说明",
            "enabledSkillIds": [], "modelId": None,
        }), 201)
        stop()

        key = "synthetic-historical-upgrade-key"
        answer = {"protocol": "openai-compatible", "baseUrl": "http://127.0.0.1:9/v1",
                  "model": "historical-answer", "apiKey": key}
        embedding = {"baseUrl": "http://127.0.0.1:9/v1", "model": "historical-index", "apiKey": key}
        configure_models({"answer": answer, "embedding": embedding})
        model_file = data / "model-settings.dpapi"
        old_models = model_file.read_bytes()
        assert key.encode() not in old_models
        assert json.loads(unprotect_bytes(old_models))["version"] == 1
        values = json.loads((data / "settings.json").read_text(encoding="utf-8"))

        def database():
            return psycopg.connect(host="127.0.0.1", port=runtime.ready["postgresPort"],
                                   user="cairn", password=values["databasePassword"], dbname="cairn")

        resource, version, chunk = uuid4(), uuid4(), uuid4()
        org = UUID(identity["organization"]["id"])
        content = "原始发布版的知识正文、引用和1024维向量必须保留。\n"
        raw = content.encode("utf-8")
        digest = hashlib.sha256(raw).hexdigest()
        object_key = f"{org}/{project}/historical.txt"
        store = LocalObjectStore(data / "objects", "http://127.0.0.1", bytes.fromhex(values["objectSecret"]))
        store.put_object(object_key=object_key, source=io.BytesIO(raw), size_bytes=len(raw),
                         content_type="text/plain", checksum_sha256=digest)
        start()
        login()
        with database() as db:
            assert db.execute("SELECT version_num FROM alembic_version").fetchone()[0] == "0023_project_scheduling"
            profile, scope = db.execute("SELECT id,scope_org_id FROM embedding_profiles WHERE status='active'").fetchone()
            db.execute("INSERT INTO knowledge_resources(id,org_id,project_id,title,source_type,source_id,external_id) "
                       "VALUES(%s,%s,%s,'historical.txt','upload','historical-proof','historical.txt')", (resource, org, project))
            db.execute("INSERT INTO knowledge_resource_versions(id,org_id,project_id,resource_id,source_type,source_id,external_id,source_version,object_key,media_type,size_bytes,sha256,parser_profile,chunking_profile,status,processing_started_at,ready_at) "
                       "VALUES(%s,%s,%s,%s,'upload','historical-proof','historical.txt','1',%s,'text/plain',%s,%s,'default-v1','default-v1','ready',now(),now())",
                       (version, org, project, resource, object_key, len(raw), digest))
            db.execute("UPDATE knowledge_resources SET current_version_id=%s WHERE id=%s", (version, resource))
            db.execute("INSERT INTO knowledge_chunks(id,org_id,project_id,resource_id,resource_version_id,ordinal,kind,text,normalized_text,locator) "
                       "VALUES(%s,%s,%s,%s,%s,0,'text',%s,%s,%s)",
                       (chunk, org, project, resource, version, content, content,
                        Jsonb({"type": "text", "headingPath": [], "lineStart": 1, "lineEnd": 1})))
            db.execute("INSERT INTO chunk_embeddings(id,org_id,project_id,resource_id,resource_version_id,chunk_id,embedding_profile_scope_org_id,embedding_profile_id,embedding) "
                       "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s::vector)",
                       (uuid4(), org, project, resource, version, chunk, scope, profile, json.dumps([1] + [0] * 1023)))

        def knowledge_snapshot():
            with database() as db:
                return db.execute(
                    "SELECT v.sha256,c.text,e.embedding::text,p.id,p.scope_org_id,p.provider_key,p.model "
                    "FROM knowledge_resource_versions v JOIN knowledge_chunks c ON c.resource_version_id=v.id "
                    "JOIN chunk_embeddings e ON e.chunk_id=c.id JOIN embedding_profiles p ON p.id=e.embedding_profile_id "
                    "WHERE v.id=%s AND v.status='ready'", (version,),
                ).fetchone()

        knowledge_before = knowledge_snapshot()
        assert knowledge_before[0] == digest and knowledge_before[1] == content
        assert len(json.loads(knowledge_before[2])) == 1024
        content_url = f"/api/v1/projects/{project}/knowledge/resources/{resource}/content"
        assert required(runtime.client.get(content_url))["content"] == content
        stop()
        passed("original runtime created account, project, task, assistant, v1 encrypted models and readable knowledge/index fixtures")

        code = work / "用户代码"
        code.mkdir()
        (code / "keep.py").write_text('print("保留用户代码")\n', encoding="utf-8")
        notes = destination / "user-notes.txt"
        notes.write_text("保留用户补充文件", encoding="utf-8")
        data_before, code_before = tree_hash(data), tree_hash(code)
        setup(args.installer, destination)
        assert registration() == {"InstallLocation": str(destination), "DisplayVersion": "0.1.1"}
        verify_payload(args.manifest)
        assert tree_hash(data) == data_before and tree_hash(code) == code_before
        assert notes.read_text(encoding="utf-8") == "保留用户补充文件"
        passed("same-directory installer upgrade replaced program files and preserved all existing data bytes")

        start()
        restored_identity = login()
        assert restored_identity["user"]["id"] == identity["user"]["id"]
        assert restored_identity["organization"]["id"] == identity["organization"]["id"]
        restored_task = required(runtime.client.get(f"/api/v1/tasks/{task['id']}"))
        assert restored_task["title"] == task["title"] and restored_task["remainingEffortMinutes"] == 90
        restored_assistant = required(runtime.client.get(f"/api/v1/projects/{project}/knowledge/assistant-settings"))
        for field in ("id", "name", "instructions", "enabledSkillIds", "modelId", "revision"):
            assert restored_assistant[field] == assistant[field], field
        assert restored_assistant["avatarDataUrl"] is None
        with database() as db:
            assert db.execute("SELECT version_num FROM alembic_version").fetchone()[0] == "0024_assistant_avatar"
        assert knowledge_snapshot() == knowledge_before
        assert required(runtime.client.get(content_url))["content"] == content
        assert runtime.ready["modelStatus"]["answerModels"][0]["id"] == "default"
        assert runtime.ready["modelStatus"]["answerModels"][0]["model"] == "historical-answer"
        assert model_file.read_bytes() == old_models, "Loading legacy model settings must not rewrite credentials"
        stop()
        passed("current runtime migrated schema 0023 to 0024 and retained original identities, tasks, assistants, knowledge, index and model binding")

        configure_models({"answerModels": [{**answer, "id": "default", "name": "迁移后的模型", "apiKey": ""}],
                          "defaultModelId": "default", "embedding": {**embedding, "apiKey": ""}})
        saved_models = json.loads(unprotect_bytes(model_file.read_bytes()))
        assert saved_models["version"] == 2
        assert saved_models["answerModels"][0]["id"] == "default"
        assert saved_models["answerModels"][0]["apiKey"] == key
        assert saved_models["embedding"]["apiKey"] == key
        assert key.encode() not in model_file.read_bytes()
        start()
        login()
        assert runtime.ready["modelStatus"]["answerModels"][0]["name"] == "迁移后的模型"
        assert knowledge_snapshot() == knowledge_before
        stop()
        passed("explicit save upgraded real v1 encrypted settings to v2 without re-entering keys or changing the existing index")

        data_before = tree_hash(data)
        setup(destination / "Uninstall.exe")
        assert registration() is None and not shortcut.exists()
        assert tree_hash(data) == data_before and tree_hash(code) == code_before
        assert notes.read_text(encoding="utf-8") == "保留用户补充文件"
        assert tree_hash(default_data) == default_before
        passed("uninstall preserved migrated data, user code and unknown files and left default user data untouched")
        (evidence / "result.json").write_text(json.dumps({
            "passed": len(checks), "baselineSha256": RELEASE_SHA256,
            "installerSha256": hashlib.sha256(args.installer.read_bytes()).hexdigest(),
            "schemaBefore": "0023_project_scheduling", "schemaAfter": "0024_assistant_avatar",
            "modelFormatBefore": 1, "modelFormatAfterExplicitSave": 2,
            "knowledgeFixture": "directly seeded persistence fixture, not live ingestion",
        }, indent=2), encoding="utf-8")
    finally:
        if runtime is not None and runtime.process is not None and runtime.process.poll() is None:
            runtime.stop()
        current = registration()
        if current is not None and current["InstallLocation"] == str(destination):
            setup(destination / "Uninstall.exe")


if __name__ == "__main__":
    main()
