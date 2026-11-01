import subprocess
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from cairn_api.authorization.types import MembershipRole
from cairn_api.db.session import Database

from .authorization_helpers import seed_actor
from .test_desktop_workspace_api import (
    DesktopFixture,
    desktop_client,
    oauth_client,
)
from .test_oauth_api import ORIGIN, password_login

__all__ = ["desktop_client", "oauth_client"]


@pytest.mark.integration
def test_file_contract_csrf_conflict_and_user_private_binding(
    desktop_client: DesktopFixture, database: Database, tmp_path: Path
) -> None:
    client, workspace, _, _, _ = desktop_client
    headers = password_login(client)
    identity = client.get("/api/v1/session").json()
    project = client.post(
        "/api/v1/projects", json={"name": "Editor contract"}, headers=headers
    ).json()["id"]
    root = tmp_path.parent / ("editor-" + str(uuid4()))
    root.mkdir()
    subprocess.run(["git", "-C", str(root), "init", "-b", "main"], check=True, capture_output=True)
    (root / "main.py").write_text("before\n")
    base = f"/api/v1/desktop/projects/{project}"
    assert (
        client.put(base + "/repository", json={"localPath": str(root)}, headers=headers).status_code
        == 200
    )
    tree = client.get(base + "/files")
    assert tree.status_code == 200 and tree.json()["paths"] == ["main.py"]
    document = client.get(base + "/file", params={"path": "main.py"})
    assert document.headers["Cache-Control"] == "no-store"
    assert document.headers["Referrer-Policy"] == "no-referrer"
    assert document.headers["X-Request-ID"]
    body = {**document.json(), "content": "saved\n"}
    denied = client.put(base + "/file", json=body, headers={"Origin": ORIGIN})
    assert denied.status_code == 403 and (root / "main.py").read_text() == "before\n"
    saved = client.put(base + "/file", json=body, headers=headers)
    assert saved.status_code == 200 and saved.json()["content"] == "saved\n"
    assert (root / "main.py").read_text() == "saved\n"
    conflict = client.put(base + "/file", json=body, headers=headers)
    assert conflict.status_code == 409 and conflict.json()["code"] == "workspace_file_conflict"
    assert conflict.json()["traceId"] == conflict.headers["X-Request-ID"]
    assert client.get(base + "/file", params={"path": "../escape"}).status_code == 422
    diff = client.get(base + "/diff", params={"path": "main.py"})
    assert (
        diff.status_code == 200
        and diff.json()["original"] == ""
        and diff.json()["modified"] == "saved\n"
    )
    assert client.get(base + "/changes").json()["files"] == [{"path": "main.py", "status": "??"}]
    viewer = seed_actor(database, MembershipRole.VIEWER, UUID(identity["organization"]["id"]))
    client.post("/api/v1/logout", headers=headers)
    login = client.post(
        "/api/v1/login",
        json={"email": viewer.email, "password": viewer.password},
        headers={"Origin": ORIGIN},
    )
    viewer_headers = {"Origin": ORIGIN, "X-CSRF-Token": login.json()["csrfToken"]}
    assert (
        client.get(base + "/file", params={"path": "main.py"}).json()["code"]
        == "workspace_not_bound"
    )
    # Even an existing local binding cannot bypass project WRITE permission.
    workspace.bind_local(viewer.user_id, UUID(project), str(root))
    assert client.get(base + "/file", params={"path": "main.py"}).status_code == 200
    assert client.put(base + "/file", json=body, headers=viewer_headers).status_code == 404
    assert (root / "main.py").read_text() == "saved\n"
