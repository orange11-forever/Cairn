"""Package an existing Windows bundle; never downloads dependencies or touches app data."""

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
REQUIRED = {
    "Cairn.exe",
    "python/python.exe",
    "postgres/bin/postgres.exe",
    "web/index.html",
    "bundle.json",
}
RESERVED = {"uninstall.exe", ".cairn-install.marker", ".cairn-owned.ini"}


def nsis_text(value: str) -> str:
    return value.replace("$", "$$").replace('"', '$\\"')


def windows(path: Path) -> str:
    return subprocess.check_output(["wslpath", "-w", str(path.resolve())], text=True).strip()


def generate_payload(bundle: Path, destination: Path) -> dict:
    files = []
    directories = []
    seen = set()
    for path in sorted(bundle.rglob("*")):
        relative = path.relative_to(bundle)
        name = relative.as_posix()
        if path.is_symlink():
            raise ValueError("Installer payload cannot contain filesystem links")
        if "__pycache__" in relative.parts or path.suffix == ".pyc":
            continue
        if any(
            any(ord(c) < 32 or c in '<>:"|?*' for c in part) or part.endswith((".", " "))
            for part in relative.parts
        ):
            raise ValueError("Payload contains a filename that is unsafe on Windows")
        if name.casefold() in seen:
            raise ValueError("Payload has Windows case-insensitive filename collisions")
        seen.add(name.casefold())
        if (
            name.casefold() in RESERVED
            or relative.name.casefold() in {"model-settings.dpapi", ".env"}
            or name.casefold() in {"settings.json", "postgres/pg_version"}
        ):
            raise ValueError("Payload contains data, credentials, or reserved installer files")
        if path.is_dir():
            directories.append(name)
        elif path.is_file():
            files.append(name)
        else:
            raise ValueError("Payload contains a nonregular file")
    if not REQUIRED.issubset(files):
        raise ValueError(
            "Bundle is incomplete: required native/Python/PostgreSQL/Web files are absent"
        )
    destination.mkdir(parents=True, exist_ok=True)
    install = ["; Generated explicit payload. No wildcard extraction."]
    for directory in directories:
        install += [
            f'CreateDirectory "$INSTDIR\\{nsis_text(directory.replace(chr(47), chr(92)))}"',
            "IfErrors install_failed",
        ]
    install_checks = []
    uninstall_checks = []
    for name in directories + files:
        target = nsis_text(name.replace("/", "\\"))
        install_checks += [f'Push "$INSTDIR\\{target}"', "Call CheckLink"]
        uninstall_checks += [f'Push "$INSTDIR\\{target}"', "Call un.CheckLink"]
    bundle_windows = windows(bundle)
    previous = None
    for name in files:
        relative = Path(name)
        parent = relative.parent.as_posix()
        if parent != previous:
            suffix = "" if parent == "." else "\\" + parent.replace("/", "\\")
            install += [
                "ClearErrors",
                f'SetOutPath "$INSTDIR{nsis_text(suffix)}"',
                "IfErrors install_failed",
            ]
            previous = parent
        target = nsis_text(name.replace("/", "\\"))
        owner_key = hashlib.sha256(name.casefold().encode("utf-8")).hexdigest()
        install_checks += [
            f'IfFileExists "$INSTDIR\\{target}" 0 ownership_{owner_key}',
            f'ReadINIStr $0 "$INSTDIR\\.cairn-owned.ini" "files" "{owner_key}"',
            f'StrCmp $0 "1" ownership_{owner_key}',
            f'!insertmacro Fail "无法确认已有文件归属，未覆盖：$INSTDIR\\{target}"',
            f"ownership_{owner_key}:",
        ]
        # Claim only preflight-checked paths so failed extraction can be repaired.
        source = nsis_text(bundle_windows + "\\" + name.replace("/", "\\"))
        install += [
            "ClearErrors",
            f'WriteINIStr "$INSTDIR\\.cairn-owned.ini" "files" "{owner_key}" "1"',
            "IfErrors install_failed",
            f'File "/oname={nsis_text(relative.name)}" "{source}"',
            "IfErrors install_failed",
        ]
    uninstall = ["; Generated ownership list. Unknown files are preserved."]
    for index, name in enumerate(files):
        target = nsis_text(name.replace("/", "\\"))
        uninstall += [
            f'IfFileExists "$INSTDIR\\{target}" 0 uninstall_next_{index}',
            "ClearErrors",
            f'Delete "$INSTDIR\\{target}"',
            "IfErrors uninstall_failed",
            f"uninstall_next_{index}:",
        ]
    for directory in sorted(directories, key=lambda value: (value.count("/"), value), reverse=True):
        uninstall.append(f'RMDir "$INSTDIR\\{nsis_text(directory.replace(chr(47), chr(92)))}"')
    (destination / "payload-check.nsh").write_text(
        "\n".join(install_checks) + "\n", encoding="utf-8"
    )
    (destination / "payload-uninstall-check.nsh").write_text(
        "\n".join(uninstall_checks) + "\n", encoding="utf-8"
    )
    (destination / "payload-install.nsh").write_text("\n".join(install) + "\n", encoding="utf-8")
    (destination / "payload-uninstall.nsh").write_text(
        "\n".join(uninstall) + "\n", encoding="utf-8"
    )
    manifest = {
        "files": files,
        "directories": directories,
        "sha256": {
            name: hashlib.sha256((bundle / name).read_bytes()).hexdigest() for name in files
        },
    }
    (destination / "payload-manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--makensis", type=Path, required=True)
    parser.add_argument("--version", default="0.1.0")
    args = parser.parse_args()
    if not re.fullmatch(r"\d+\.\d+\.\d+", args.version):
        parser.error("version must be a numeric major.minor.patch")
    bundle = args.bundle.resolve()
    output = args.output.resolve()
    if output.is_relative_to(bundle):
        parser.error("Installer output must be outside the source bundle")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="cairn-installer-", dir=output.parent) as temporary:
        working = Path(temporary)
        generate_payload(bundle, working)
        shutil.copy2(ROOT / "apps/desktop/windows/Cairn.nsi", working / "Cairn.nsi")
        shutil.copy2(ROOT / "apps/desktop/windows/Cairn.ico", working / "Cairn.ico")
        script = working / "build.nsi"
        script.write_text(
            f'!define OUTPUT_FILE "{nsis_text(windows(output))}"\n!define APP_VERSION "{args.version}"\n!include "Cairn.nsi"\n',
            encoding="utf-8",
        )
        subprocess.run(
            [str(args.makensis.resolve()), "/V2", windows(script)], cwd=working, check=True
        )
        shutil.copy2(working / "payload-manifest.json", output.with_suffix(".manifest.json"))
    print("Built " + str(output))


if __name__ == "__main__":
    main()
