import runpy
from pathlib import Path

import pytest

TOOL = Path(__file__).resolve().parents[1] / "tools/build_installer.py"


def bundle_at(directory):
    for name in [
        "Cairn.exe",
        "python/python.exe",
        "postgres/bin/postgres.exe",
        "web/index.html",
        "bundle.json",
        "app/main.py",
        "empty/.keep",
    ]:
        path = directory / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"owned-program-content")
    return directory


def test_generated_uninstall_only_names_owned_files_and_nonrecursive_directories(tmp_path):
    tool = runpy.run_path(str(TOOL))
    bundle = bundle_at(tmp_path / "bundle")
    target = tmp_path / "generated"
    target.mkdir()
    manifest = tool["generate_payload"](bundle, target)
    uninstall = (target / "payload-uninstall.nsh").read_text()
    assert set(manifest["files"]) == {
        "Cairn.exe",
        "python/python.exe",
        "postgres/bin/postgres.exe",
        "web/index.html",
        "bundle.json",
        "app/main.py",
        "empty/.keep",
    }
    assert 'Delete "$INSTDIR\\app\\main.py"' in uninstall
    assert 'RMDir "$INSTDIR\\postgres\\bin"' in uninstall
    assert "RMDir /r" not in uninstall and 'Delete "$INSTDIR\\*' not in uninstall
    assert "$LOCALAPPDATA" not in uninstall and "settings.json" not in uninstall


@pytest.mark.parametrize(
    "name",
    [
        "settings.json",
        "model-settings.dpapi",
        "postgres/PG_VERSION",
        ".cairn-install.marker",
        "Uninstall.exe",
        ".cairn-owned.ini",
        "Settings.JSON",
        "app/MODEL-SETTINGS.DPAPI",
    ],
)
def test_payload_refuses_data_or_reserved_installer_ownership_files(tmp_path, name):
    tool = runpy.run_path(str(TOOL))
    bundle = bundle_at(tmp_path / "bundle")
    path = bundle / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"do-not-package")
    with pytest.raises(ValueError):
        tool["generate_payload"](bundle, tmp_path / "generated")


def test_payload_rejects_links_and_windows_case_collisions(tmp_path):
    tool = runpy.run_path(str(TOOL))
    bundle = bundle_at(tmp_path / "bundle")
    (bundle / "app/linked").symlink_to(tmp_path)
    with pytest.raises(ValueError):
        tool["generate_payload"](bundle, tmp_path / "generated")
    (bundle / "app/linked").unlink()
    (bundle / "APP").mkdir()
    (bundle / "APP/main.py").write_bytes(b"collision")
    with pytest.raises(ValueError):
        tool["generate_payload"](bundle, tmp_path / "generated")
