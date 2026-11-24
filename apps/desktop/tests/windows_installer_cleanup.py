"""Real install/uninstall cleanup checks using disposable Windows directories."""

import argparse
import ctypes
import hashlib
import json
import os
import runpy
import subprocess
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("baseline", "baseline-manifest", "installer", "manifest", "work"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    assert hashlib.sha256(args.baseline.read_bytes()).hexdigest() == "1d601b86fffa6be65dd2ac195228d062ecd35c43ef9c32099dad7b6393a133e8"
    support = runpy.run_path(str(Path(__file__).with_name("windows_installer.py")))
    registration, setup, tree_hash = (support[name] for name in ("registration", "setup", "tree_hash"))
    assert registration() is None, "Existing installation must not be touched"
    assert not support["running_signal"](), "Close the preview before installer checks"
    shortcut = Path(os.environ["APPDATA"]) / "Microsoft/Windows/Start Menu/Programs/Cairn.lnk"
    assert not shortcut.exists(), "Existing shortcut must not be touched"
    args.work.mkdir(parents=True, exist_ok=False)
    work = args.work.resolve()
    evidence = work / "evidence"
    evidence.mkdir()
    previous = json.loads(args.baseline_manifest.read_text(encoding="utf-8"))
    current = json.loads(args.manifest.read_text(encoding="utf-8"))
    Runtime = runpy.run_path(str(Path(__file__).with_name("windows_smoke.py")))["Runtime"]
    default_data = Path(os.environ["LOCALAPPDATA"]) / "Cairn/DesktopPrototype"
    default_before = tree_hash(default_data)
    programs = []
    checks = []
    cache_counts = []
    runtime = None
    held = None

    def passed(label):
        checks.append(label)
        (evidence / "checks.json").write_text(json.dumps(checks, indent=2), encoding="utf-8")
        print("PASS " + label, flush=True)

    def boot(program, data):
        nonlocal runtime
        runtime = Runtime(program, data, evidence, python=program / "python/python.exe")
        runtime.start()
        runtime.stop()
        runtime = None

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32,
                                  ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p]
    kernel.CreateFileW.restype = ctypes.c_void_p
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    try:
        program, data = work / "upgraded program", work / "retained data 中文"
        programs.append(program)
        setup(args.baseline, program)
        boot(program, data)
        setup(args.installer, program)
        assert registration() == {"InstallLocation": str(program), "DisplayVersion": "0.1.1"}
        for name, digest in current["sha256"].items():
            assert hashlib.sha256((program / name).read_bytes()).hexdigest() == digest, name
        boot(program, data)
        caches = [file.relative_to(program) for file in program.rglob("*.pyc")]
        assert caches, "Runtime must generate real program caches"
        cache_counts.append(len(caches))
        obsolete = sorted(set(previous["files"]) - set(current["files"]))
        assert obsolete and all((program / name).is_file() for name in obsolete)
        passed("original release upgraded with its real stale assets and runtime-generated caches present")

        extras = {
            "user-notes.txt": b"preserve user notes",
            "app/user_extension.py": b"# preserve user extension\n",
            "app/__pycache__/user_extension.cpython-313.pyc": b"preserve user extension cache",
            "user-data/settings.json": b'{"preserve":"user data"}',
        }
        for name, content in extras.items():
            target = program / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        outside = work / "outside-user-data"
        outside.mkdir()
        (outside / "keep.txt").write_bytes(b"do not traverse this junction")
        junction = program / "extra-link"
        subprocess.run(["cmd.exe", "/d", "/c", "mklink", "/J", str(junction), str(outside)],
                       capture_output=True, check=True)
        data_before = tree_hash(data)
        held = kernel.CreateFileW(str(program / obsolete[0]), 0x80000000, 0, None, 3, 0x80, None)
        assert held not in (None, ctypes.c_void_p(-1).value), ctypes.get_last_error()
        setup(program / "Uninstall.exe", success=False)
        assert registration() == {"InstallLocation": str(program), "DisplayVersion": "0.1.1"}
        assert (program / "Cairn.exe").is_file() and (program / ".cairn-owned.ini").is_file()
        assert shortcut.exists() and tree_hash(data) == data_before
        kernel.CloseHandle(held)
        held = None
        passed("locked obsolete file rejects uninstall without losing current program, registration, ownership or data")

        setup(program / "Uninstall.exe")
        assert registration() is None and not shortcut.exists()
        for name in set(previous["files"]) | set(current["files"]):
            assert not (program / name).exists(), name
        for name in caches:
            assert not (program / name).exists(), str(name)
        for name in ("Uninstall.exe", ".cairn-install.marker", ".cairn-owned.ini"):
            assert not (program / name).exists(), name
        for name, content in extras.items():
            assert (program / name).read_bytes() == content, name
        assert junction.is_junction() and (outside / "keep.txt").read_bytes() == b"do not traverse this junction"
        assert tree_hash(data) == data_before
        passed("uninstall removes current/legacy owned payload and all owned caches while preserving extra files, data and junction targets")

        program, data = work / "fresh program", work / "fresh data 中文"
        programs.append(program)
        setup(args.installer, program)
        boot(program, data)
        caches = list(program.rglob("*.pyc"))
        assert caches
        cache_counts.append(len(caches))
        data_before = tree_hash(data)
        setup(program / "Uninstall.exe")
        assert not program.exists(), "Fresh installation directory must be completely removed"
        assert registration() is None and not shortcut.exists()
        assert tree_hash(data) == data_before and tree_hash(default_data) == default_before
        passed("fresh install/start/uninstall removes the whole program directory and retains application and existing default data")
        (evidence / "result.json").write_text(json.dumps({
            "passed": len(checks), "ownedCacheCounts": cache_counts,
            "legacyAssetCount": len(obsolete),
            "installerSha256": hashlib.sha256(args.installer.read_bytes()).hexdigest(),
        }, indent=2), encoding="utf-8")
    finally:
        if held is not None:
            kernel.CloseHandle(held)
        if runtime is not None and runtime.process is not None and runtime.process.poll() is None:
            runtime.stop()
        registered = registration()
        if registered is not None and any(registered["InstallLocation"] == str(program) for program in programs):
            setup(Path(registered["InstallLocation"]) / "Uninstall.exe")


if __name__ == "__main__":
    main()
