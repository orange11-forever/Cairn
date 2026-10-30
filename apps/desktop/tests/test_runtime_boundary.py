from pathlib import Path

from cairn_api.app import CairnFastAPI
from fastapi.testclient import TestClient


def test_only_the_native_application_can_reach_local_routes():
    from cairn_desktop.http import DesktopAccess

    app = CairnFastAPI()

    @app.get("/private")
    def private():
        return {"private": "project"}

    app.add_middleware(DesktopAccess, origin="http://127.0.0.1:8088", token="test-capability")
    with TestClient(app, base_url="http://127.0.0.1:8088") as client:
        denied = client.get("/private")
        assert denied.status_code == 403
        assert denied.json()["code"] == "desktop_access_denied"
        assert denied.json()["traceId"] == denied.headers["X-Request-ID"]
        assert denied.headers["Referrer-Policy"] == "no-referrer"
        assert denied.headers["X-Content-Type-Options"] == "nosniff"
        headers = {"X-Cairn-Desktop": "test-capability"}
        assert client.get("/private", headers=headers).json() == {"private": "project"}
        assert (
            client.get("/private", headers={**headers, "Host": "attacker.test:8088"}).status_code
            == 403
        )
        assert (
            client.get(
                "/private", headers={**headers, "Origin": "https://attacker.test"}
            ).status_code
            == 403
        )
        assert (
            client.get("/private", headers={**headers, "Sec-Fetch-Site": "cross-site"}).status_code
            == 403
        )
        client.cookies.set("cairn_desktop_8088", "test-capability")
        assert client.get("/private").status_code == 200
        client.cookies.set("cairn_desktop_8088", "old-capability")
        assert client.get("/private").status_code == 403


def test_backup_roundtrip_and_restore_never_overwrites_existing_data(tmp_path: Path):
    from cairn_desktop.data import backup_data, restore_data

    data = tmp_path / "original"
    (data / "postgres").mkdir(parents=True)
    (data / "postgres" / "pg_tblspc").mkdir()
    (data / "postgres" / "PG_VERSION").write_text("18\n")
    (data / "objects" / "org").mkdir(parents=True)
    (data / "objects" / "org" / "body").write_bytes(b"retained object")
    (data / "settings.json").write_text('{"version": 1}')
    (data / "logs").mkdir()
    (data / "logs" / "private.log").write_text("excluded")
    (data / "model-settings.dpapi").write_bytes(b"encrypted-model-credentials-excluded")
    archive = tmp_path / "backup.cairn"
    backup_data(data, archive)
    restored = tmp_path / "restored"
    restore_data(archive, restored)
    assert (restored / "objects" / "org" / "body").read_bytes() == b"retained object"
    assert (restored / "postgres" / "PG_VERSION").read_text() == "18\n"
    assert (restored / "postgres" / "pg_tblspc").is_dir()
    assert not (restored / "logs").exists()
    assert not (restored / "model-settings.dpapi").exists()
    import pytest

    with pytest.raises(ValueError, match="empty|exist"):
        restore_data(archive, restored)
    assert (restored / "objects" / "org" / "body").read_bytes() == b"retained object"


def test_corrupt_and_traversal_backups_leave_no_partial_destination(tmp_path: Path):
    import json
    import zipfile

    import pytest
    from cairn_desktop.data import restore_data

    for name in ["../escape", "postgres/PG_VERSION"]:
        archive = tmp_path / "bad.cairn"
        with zipfile.ZipFile(archive, "w") as output:
            output.writestr(
                "manifest.json",
                json.dumps(
                    {
                        "format": 1,
                        "platform": "win32",
                        "postgres": "18",
                        "files": {name: {"size": 3, "sha256": "0" * 64}},
                        "directories": [],
                    }
                ),
            )
            output.writestr(name, b"bad")
        destination = tmp_path / "restored"
        with pytest.raises(ValueError):
            restore_data(archive, destination)
        assert not destination.exists()
        assert not (tmp_path / "escape").exists()


def test_data_lock_refuses_second_owner_and_releases_on_exit(tmp_path: Path):
    import pytest
    from cairn_desktop.data import DataLock

    with DataLock(tmp_path), pytest.raises(RuntimeError, match="already"), DataLock(tmp_path):
        pass
    with DataLock(tmp_path):
        pass


def test_startup_refuses_an_unrelated_nonempty_directory(tmp_path: Path):
    import pytest
    from cairn_desktop.data import validate_data_directory

    unrelated = tmp_path / "documents"
    unrelated.mkdir()
    sentinel = unrelated / "keep.txt"
    sentinel.write_text("user document")
    with pytest.raises(ValueError, match="empty|Cairn"):
        validate_data_directory(unrelated)
    assert sentinel.read_text() == "user document"
    assert list(unrelated.iterdir()) == [sentinel]
    validate_data_directory(tmp_path / "new-data")
