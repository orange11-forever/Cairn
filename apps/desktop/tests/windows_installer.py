"""Run with a separate bundled Windows Python; never uses an existing installation.

The baseline is a test-only earlier-version installer with a different README.
Both installers contain a complete runtime. All application data uses a new --work.
"""

import argparse
import ctypes
import hashlib
import json
import os
import runpy
import secrets
import shutil
import subprocess
import tempfile
import time
import winreg
from pathlib import Path

KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\CairnDesktop"
KERNEL = ctypes.WinDLL("kernel32", use_last_error=True)
KERNEL.OpenMutexW.argtypes = [ctypes.c_uint32, ctypes.c_bool, ctypes.c_wchar_p]
KERNEL.OpenMutexW.restype = ctypes.c_void_p
KERNEL.CloseHandle.argtypes = [ctypes.c_void_p]
USER = ctypes.WinDLL("user32", use_last_error=True)
CALLBACK = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
USER.EnumWindows.argtypes = [CALLBACK, ctypes.c_void_p]
USER.EnumChildWindows.argtypes = [ctypes.c_void_p, CALLBACK, ctypes.c_void_p]
USER.GetWindowThreadProcessId.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)]
USER.PostMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_void_p]
USER.GetWindowTextW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int]
USER.IsWindowVisible.argtypes = [ctypes.c_void_p]


def registration():
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, KEY, access=winreg.KEY_READ | winreg.KEY_WOW64_64KEY
        ) as key:
            return {
                name: winreg.QueryValueEx(key, name)[0]
                for name in ("InstallLocation", "DisplayVersion")
            }
    except FileNotFoundError:
        return None


def setup(executable, destination=None, *, success=True):
    if destination is None:
        # NSIS's normal uninstaller launcher returns before its child and discards
        # the child's exit code. Follow the documented copy + _?= procedure to
        # observe the actual uninstaller while allowing it to delete its original.
        # https://nsis.sourceforge.io/Docs/AppendixD.html#D.1
        with tempfile.TemporaryDirectory(prefix="cairn-uninstall-proof-") as temporary:
            copied = Path(temporary) / "Uninstall.exe"
            shutil.copy2(executable, copied)
            result = subprocess.run(
                f'"{copied}" /S _?={executable.parent}', timeout=300, check=False
            )
    else:
        # NSIS requires /D= last and unquoted, including paths containing spaces.
        result = subprocess.run(f'"{executable}" /S /D={destination}', timeout=300, check=False)
    assert (result.returncode == 0) == success, (str(executable), result.returncode, success)


def tree_hash(root):
    if not root.exists():
        return None
    result = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink() or path.is_junction():
            result[path.relative_to(root).as_posix()] = "link:" + str(path.readlink())
        elif path.is_file():
            result[path.relative_to(root).as_posix()] = hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
    return result


def running_signal():
    handle = KERNEL.OpenMutexW(0x100000, False, r"Local\Cairn.Desktop.Running.v1")
    if handle:
        KERNEL.CloseHandle(handle)
        return True
    return False


def close_native(process, *, require_ready=True):
    # The running mutex precedes startup. Closing while the startup label is
    # visible correctly opens the app's busy dialog, so await the real UI state.
    deadline = time.monotonic() + 120
    main_window = None
    while True:
        visible_text = []

        @CALLBACK
        def text(window, _, values=visible_text):
            if USER.IsWindowVisible(window):
                buffer = ctypes.create_unicode_buffer(4096)
                USER.GetWindowTextW(window, buffer, len(buffer))
                values.append(buffer.value)
            return True

        @CALLBACK
        def inspect(window, _):
            nonlocal main_window
            pid = ctypes.c_uint32()
            USER.GetWindowThreadProcessId(window, ctypes.byref(pid))
            if pid.value == process.pid and USER.IsWindowVisible(window):
                buffer = ctypes.create_unicode_buffer(256)
                USER.GetWindowTextW(window, buffer, len(buffer))
                if buffer.value == "Cairn · 桌面样机":
                    main_window = window
                    USER.EnumChildWindows(window, text, None)
            return True

        USER.EnumWindows(inspect, None)
        if require_ready:
            assert not any("Cairn 未能继续运行" in value for value in visible_text), visible_text
        if main_window and not any("正在启动" in value for value in visible_text):
            break
        assert process.poll() is None and time.monotonic() < deadline, (
            "native UI did not finish startup"
        )
        time.sleep(0.1)

    @CALLBACK
    def close(window, _):
        pid = ctypes.c_uint32()
        USER.GetWindowThreadProcessId(window, ctypes.byref(pid))
        if pid.value == process.pid and window == main_window:
            USER.PostMessageW(window, 0x10, None, None)
        return True

    USER.EnumWindows(close, None)
    assert process.wait(timeout=120) == 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--installer", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--work", type=Path, required=True)
    args = parser.parse_args()
    assert registration() is None, "Existing installation must not be touched"
    assert not running_signal(), "Close existing Cairn before isolated acceptance"
    shortcut = Path(os.environ["APPDATA"]) / "Microsoft/Windows/Start Menu/Programs/Cairn.lnk"
    assert not shortcut.exists(), "Existing shortcut must not be touched"
    args.work.mkdir(parents=True, exist_ok=False)
    work = args.work.resolve()
    evidence = work / "evidence"
    evidence.mkdir()
    destination = work / "program with spaces"
    data = work / "custom data 中文"
    default_data = Path(os.environ["LOCALAPPDATA"]) / "Cairn/DesktopPrototype"
    original_default = tree_hash(default_data)
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    Runtime = runpy.run_path(str(Path(__file__).with_name("windows_smoke.py")))["Runtime"]
    runtime = native = None
    checks = []

    def passed(name):
        checks.append(name)
        (evidence / "checks.json").write_text(
            json.dumps(checks, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print("PASS " + name, flush=True)

    def verify_payload():
        for name, expected in manifest["sha256"].items():
            assert hashlib.sha256((destination / name).read_bytes()).hexdigest() == expected, name

    def start():
        return Runtime(
            destination, data, evidence, python=destination / "python/python.exe"
        ).start()

    try:
        nonempty = work / "unowned"
        nonempty.mkdir()
        (nonempty / "keep.txt").write_bytes(b"unowned user file")
        before = tree_hash(nonempty)
        setup(args.installer, nonempty, success=False)
        assert tree_hash(nonempty) == before
        passed("nonempty unmarked destination refused without changes")

        unicode_program = work / "program 中文"
        setup(args.installer, unicode_program, success=False)
        assert not unicode_program.exists()
        passed("unsupported non-ASCII program path rejected before creating files")

        setup(args.baseline, destination)
        assert registration() == {"InstallLocation": str(destination), "DisplayVersion": "0.0.0"}
        assert shortcut.exists()
        assert (
            (destination / "README.md")
            .read_bytes()
            .startswith(b"INSTALLER ACCEPTANCE BASELINE ONLY")
        )
        passed("per-user first install into a path with spaces")

        runtime = start()
        email, password = "installer-acceptance@example.com", secrets.token_urlsafe(24)
        result = runtime.client.post(
            "/api/v1/auth/register",
            json={"email": email, "password": password, "displayName": "安装验收"},
        )
        assert result.status_code == 201, result.text

        def login(instance):
            response = instance.client.post(
                "/api/v1/login", json={"email": email, "password": password}
            )
            assert response.status_code == 200, response.text
            instance.client.headers["X-CSRF-Token"] = response.json()["csrfToken"]

        login(runtime)
        result = runtime.client.post("/api/v1/projects", json={"name": "安装更新后保留"})
        assert result.status_code == 201, result.text
        project = result.json()["id"]
        result = runtime.client.post(
            f"/api/v1/projects/{project}/tasks",
            json={"title": "更新卸载不丢失", "remainingEffortMinutes": 90},
        )
        assert result.status_code == 201, result.text
        task = result.json()["id"]
        runtime.stop()
        runtime = None
        key = "synthetic-installer-preservation-key"
        result = subprocess.run(
            [
                str(destination / "python/python.exe"),
                "-X",
                "utf8",
                "-m",
                "cairn_desktop.runtime",
                "model-configure",
                "--bundle",
                str(destination),
                "--data",
                str(data),
            ],
            input=json.dumps(
                {
                    "answer": {
                        "protocol": "openai-responses",
                        "baseUrl": "http://127.0.0.1:9/v1",
                        "model": "合成验收模型",
                        "apiKey": key,
                    },
                    "embedding": None,
                }
            ),
            text=True,
            capture_output=True,
            timeout=180,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        assert key.encode() not in (data / "model-settings.dpapi").read_bytes()
        passed(
            "installed runtime registers, persists project/task and encrypts synthetic model settings"
        )

        unknown = destination / "app/user-notes.txt"
        unknown.write_bytes(b"unknown personal notes")
        nested_data = destination / "my-data"
        nested_data.mkdir()
        (nested_data / "settings.json").write_bytes(b"custom data must survive")
        unknown_before = tree_hash(nested_data)
        data_before = tree_hash(data)
        before = tree_hash(destination)
        setup(args.installer, data, success=False)
        assert tree_hash(data) == data_before
        passed("custom data directory refused as installation target")

        native = subprocess.Popen(
            [str(destination / "Cairn.exe"), "--data", str(data)], cwd=destination
        )
        deadline = time.monotonic() + 45
        while not running_signal():
            assert native.poll() is None and time.monotonic() < deadline, (
                "native launcher did not publish running state"
            )
            time.sleep(0.1)
        setup(args.installer, destination, success=False)
        setup(destination / "Uninstall.exe", success=False)
        # Runtime may create Python caches, so compare owned payload only.
        for name in manifest["files"]:
            if name != "README.md":
                assert (
                    hashlib.sha256((destination / name).read_bytes()).hexdigest() == before[name]
                ), name
        close_native(native)
        native = None
        assert not running_signal()
        passed("actual native process blocks update and uninstall, then closes normally")

        data_before = tree_hash(data)
        setup(args.installer, destination)
        verify_payload()
        assert registration() == {"InstallLocation": str(destination), "DisplayVersion": "0.1.0"}
        assert tree_hash(data) == data_before
        assert (
            tree_hash(nested_data) == unknown_before
            and unknown.read_bytes() == b"unknown personal notes"
        )
        passed(
            "manual same-directory version update replaces payload and preserves every data/config byte"
        )

        runtime = start()
        login(runtime)
        result = runtime.client.get(f"/api/v1/tasks/{task}")
        assert result.status_code == 200 and result.json()["title"] == "更新卸载不丢失"
        assert result.json()["remainingEffortMinutes"] == 90
        assert runtime.ready["modelStatus"]["answer"]["model"] == "合成验收模型"
        runtime.stop()
        runtime = None
        passed(
            "updated installed runtime reopens the original account, task and model configuration"
        )

        data_before = tree_hash(data)
        setup(destination / "Uninstall.exe")
        assert registration() is None and not shortcut.exists()
        assert not (destination / "Cairn.exe").exists()
        assert tree_hash(data) == data_before
        assert (
            tree_hash(nested_data) == unknown_before
            and unknown.read_bytes() == b"unknown personal notes"
        )
        assert tree_hash(default_data) == original_default
        passed(
            "uninstall removes owned program/registration/shortcut and preserves default, custom and unknown data"
        )
        (evidence / "result.json").write_text(
            json.dumps(
                {
                    "passed": len(checks),
                    "installerSha256": hashlib.sha256(args.installer.read_bytes()).hexdigest(),
                    "project": project,
                    "task": task,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
    finally:
        if runtime is not None and runtime.process.poll() is None:
            runtime.stop()
        if native is not None and native.poll() is None:
            close_native(native, require_ready=False)
        if registration() == {
            "InstallLocation": str(destination),
            "DisplayVersion": "0.0.0",
        } or registration() == {"InstallLocation": str(destination), "DisplayVersion": "0.1.0"}:
            setup(destination / "Uninstall.exe")


if __name__ == "__main__":
    main()
