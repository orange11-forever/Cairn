import runpy
from pathlib import Path

import pytest

TOOL = Path(__file__).resolve().parents[1] / "tools/build_installer.py"


def bundle_at(directory):
    for name in [
        "Cairn.exe",
        "Microsoft.Web.WebView2.Core.dll",
        "Microsoft.Web.WebView2.WinForms.dll",
        "WebView2Loader.dll",
        "python/python.exe",
        "python/python313.dll",
        "python/python313.zip",
        "python/python313._pth",
        "python/vcruntime140.dll",
        "python/vcruntime140_1.dll",
        "postgres/bin/postgres.exe",
        "postgres/bin/initdb.exe",
        "postgres/bin/pg_ctl.exe",
        "postgres/lib/vector.dll",
        "postgres/share/extension/vector.control",
        "postgres/share/extension/vector--0.8.7.sql",
        "app/cairn_desktop/runtime.py",
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
    assert len(manifest["files"]) == 21
    assert "WebView2Loader.dll" in manifest["files"]
    assert 'Delete "$INSTDIR\\app\\main.py"' in uninstall
    assert 'RMDir "$INSTDIR\\postgres\\bin"' in uninstall
    assert "RMDir /r" not in uninstall and 'Delete "$INSTDIR\\*' not in uninstall
    assert "$LOCALAPPDATA" not in uninstall and "settings.json" not in uninstall


@pytest.mark.parametrize("missing", ["WebView2Loader.dll", "postgres/lib/vector.dll", "python/python313.dll"])
def test_payload_refuses_missing_runtime_dependencies(tmp_path, missing):
    tool = runpy.run_path(str(TOOL))
    bundle = bundle_at(tmp_path / "bundle")
    (bundle / missing).unlink()
    with pytest.raises(ValueError, match="Bundle is incomplete"):
        tool["generate_payload"](bundle, tmp_path / "generated")


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
