"""Build the Windows feasibility bundle from WSL; no system installation is changed.

Inputs: the pinned downloads and Windows wheels in .superpowers/desktop-*.
PostgreSQL's installed bin/lib/share are copied, never its data directory.
"""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[3]


def windows(path: Path) -> str:
    return subprocess.check_output(["wslpath", "-w", str(path.resolve())], text=True).strip()


def run_batch(path: Path, lines: list[str]):
    path.write_bytes(("@echo off\r\n" + "\r\n".join(lines) + "\r\n").encode())
    subprocess.run(["/mnt/c/Windows/System32/cmd.exe", "/d", "/c", windows(path)], check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--code-only",
        action="store_true",
        help="Reuse this bundle's already built third-party runtime",
    )
    parser.add_argument("--postgres", type=Path, default=Path("/mnt/c/Program Files/PostgreSQL/18"))
    parser.add_argument(
        "--vcvars",
        type=Path,
        default=Path(
            "/mnt/d/Program Files/Microsoft Visual Studio/2022/Community/VC/Auxiliary/Build/vcvars64.bat"
        ),
    )
    args = parser.parse_args()
    bundle = args.output.resolve()
    bundle.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / "LICENSE", bundle / "CAIRN-LICENSE.txt")
    downloads = ROOT / ".superpowers/desktop-downloads"
    build = ROOT / ".superpowers/desktop-build"
    # Copy only the disposable bundle's known runtime directories on subsequent builds.
    for source, target in [
        (ROOT / "apps/desktop/src/cairn_desktop", bundle / "app/cairn_desktop"),
        (ROOT / "apps/api/src/cairn_api", bundle / "app/cairn_api"),
        (ROOT / "apps/worker/src/cairn_worker", bundle / "app/cairn_worker"),
        (ROOT / "apps/api/migrations", bundle / "migrations"),
    ]:
        shutil.copytree(
            source,
            target,
            dirs_exist_ok=True,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )
    native = bundle.parent / "native-build"
    native.mkdir(exist_ok=True)
    if not args.code_only:
        for name in ("bin", "lib", "share"):
            shutil.copytree(args.postgres / name, bundle / "postgres" / name, dirs_exist_ok=True)
        for name in ("server_license.txt", "commandlinetools_3rd_party_licenses.txt"):
            shutil.copy2(args.postgres / name, bundle / "postgres" / name)
        with ZipFile(downloads / "python-3.13.17-embed-amd64.zip") as archive:
            archive.extractall(bundle / "python")
        shutil.copytree(
            build / "python-libs", bundle / "python/Lib/site-packages", dirs_exist_ok=True
        )
        (bundle / "python/python313._pth").write_text(
            "python313.zip\n.\nLib/site-packages\n../app\nimport site\n"
        )
        with ZipFile(downloads / "pgvector-0.8.7.zip") as archive:
            archive.extractall(native)
        vector = native / "pgvector-0.8.7"
        run_batch(
            native / "vector.cmd",
            [
                'call "' + windows(args.vcvars) + '" >nul',
                "if errorlevel 1 exit /b 1",
                'set "PGROOT=' + windows(args.postgres) + '"',
                'cd /d "' + windows(vector) + '"',
                "nmake /nologo /F Makefile.win OPTFLAGS=/O2",
                "if errorlevel 1 exit /b 1",
            ],
        )
        shutil.copy2(vector / "vector.dll", bundle / "postgres/lib/vector.dll")
        shutil.copy2(vector / "vector.control", bundle / "postgres/share/extension/vector.control")
        for path in (vector / "sql").glob("*.sql"):
            shutil.copy2(path, bundle / "postgres/share/extension" / path.name)
        shutil.copy2(vector / "LICENSE", bundle / "postgres/pgvector-LICENSE")
        with ZipFile(downloads / "webview2-1.0.4258.31.zip") as archive:
            for name in [
                "lib/net462/Microsoft.Web.WebView2.Core.dll",
                "lib/net462/Microsoft.Web.WebView2.WinForms.dll",
                "runtimes/win-x64/native/WebView2Loader.dll",
                "LICENSE.txt",
            ]:
                (bundle / Path(name).name).write_bytes(archive.read(name))
    shutil.copy2(ROOT / "apps/desktop/windows/Cairn.cs", native / "Cairn.cs")
    shutil.copy2(ROOT / "apps/desktop/windows/Cairn.ico", native / "Cairn.ico")
    run_batch(
        native / "shell.cmd",
        [
            'cd /d "' + windows(bundle) + '"',
            '"'
            + windows(args.vcvars.parents[3] / "MSBuild/Current/Bin/Roslyn/csc.exe")
            + '" /nologo /target:winexe /platform:x64 /out:Cairn.exe '
            + '/win32icon:"'
            + windows(native / "Cairn.ico")
            + '" '
            + "/reference:System.Windows.Forms.dll /reference:System.Drawing.dll /reference:System.Web.Extensions.dll "
            '/reference:Microsoft.Web.WebView2.Core.dll /reference:Microsoft.Web.WebView2.WinForms.dll "'
            + windows(native / "Cairn.cs")
            + '"',
            "if errorlevel 1 exit /b 1",
        ],
    )
    subprocess.run(
        ["pnpm", "exec", "vite", "build", "--emptyOutDir", "--outDir", str(bundle / "web")],
        cwd=ROOT / "apps/web",
        env={**os.environ, "VITE_IDENTITY_API_URL": ""},
        check=True,
    )
    manifest = {
        "platform": "win32-x64",
        "python": "3.13.17",
        "postgres": "18",
        "pgvector": "0.8.7",
        "webview2Sdk": "1.0.4258.31",
        "downloads": {},
    }
    for name in (
        "python-3.13.17-embed-amd64.zip",
        "pgvector-0.8.7.zip",
        "webview2-1.0.4258.31.zip",
    ):
        with (downloads / name).open("rb") as source:
            manifest["downloads"][name] = hashlib.file_digest(source, "sha256").hexdigest()
    (bundle / "bundle.json").write_text(json.dumps(manifest, indent=2))
    print("Built " + str(bundle / "Cairn.exe"))


if __name__ == "__main__":
    main()
