"""Single-owner data directories and cold, checksummed local backups."""

import hashlib
import json
import os
import shutil
import stat
import tempfile
import zipfile
from pathlib import Path, PurePosixPath


def validate_data_directory(directory: Path) -> None:
    if (
        directory.exists()
        and not (directory / "settings.json").is_file()
        and any(directory.iterdir())
    ):
        raise ValueError("Choose an empty directory or an existing Cairn data directory")


class DataLock:
    def __init__(self, directory: Path):
        self.directory = directory
        self.handle = None

    def __enter__(self):
        self.directory.mkdir(parents=True, exist_ok=True)
        self.handle = (self.directory / ".owner.lock").open("a+b")
        self.handle.seek(0)
        if self.handle.read(1) == b"":
            self.handle.write(b"0")
            self.handle.flush()
        self.handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            self.handle.close()
            raise RuntimeError("This Cairn data directory is already in use") from error
        return self

    def __exit__(self, *_):
        self.handle.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(self.handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(self.handle, fcntl.LOCK_UN)
        self.handle.close()


def digest_file(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def backup_data(directory: Path, destination: Path) -> None:
    """Caller holds DataLock and has confirmed a clean database shutdown."""
    directory = directory.resolve()
    destination = destination.resolve()
    if destination.is_relative_to(directory) or destination.exists():
        raise ValueError("Backup destination must be a new file outside the data directory")
    if (directory / "postgres" / "postmaster.pid").exists():
        raise ValueError("Stop Cairn before backing up its database")
    if (directory / "postgres" / "PG_VERSION").read_text().strip() != "18":
        raise ValueError("This prototype only backs up PostgreSQL 18 data")
    files = [directory / "settings.json"]
    directories = []
    for name in ("postgres", "objects"):
        for path in [directory / name, *(directory / name).rglob("*")]:
            if path.is_symlink() or not path.resolve().is_relative_to(directory):
                raise ValueError("Backup cannot include filesystem links")
            if path.is_dir():
                directories.append(path.relative_to(directory).as_posix())
            elif path.exists():
                files.append(path)
    manifest = {
        "format": 1,
        "platform": "win32",
        "postgres": "18",
        "files": {},
        "directories": directories,
    }
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as handle:
            temporary = Path(handle.name)
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in files:
                if path.is_symlink() or not path.resolve().is_relative_to(directory):
                    raise ValueError("Backup cannot include links outside the data directory")
                name = path.relative_to(directory).as_posix()
                manifest["files"][name] = {"size": path.stat().st_size, "sha256": digest_file(path)}
                archive.write(path, name)
            archive.writestr("manifest.json", json.dumps(manifest))
        # Publish without replacing an existing backup, including a concurrent writer.
        os.link(temporary, destination)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def restore_data(archive_path: Path, destination: Path) -> None:
    """Restore into a new directory only; never touch an existing installation."""
    destination = destination.resolve()
    if destination.exists():
        raise ValueError("Restore destination must not exist")
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".cairn-restore-", dir=destination.parent))
    try:
        with zipfile.ZipFile(archive_path) as archive:
            if archive.getinfo("manifest.json").file_size > 16 * 1024 * 1024:
                raise ValueError("Backup manifest is too large")
            manifest = json.loads(archive.read("manifest.json"))
            if (
                not isinstance(manifest, dict)
                or manifest.get("format") != 1
                or manifest.get("platform") != "win32"
                or manifest.get("postgres") != "18"
                or not isinstance(manifest.get("files"), dict)
                or not isinstance(manifest.get("directories"), list)
                or not all(isinstance(name, str) for name in manifest["directories"])
            ):
                raise ValueError("Unsupported Cairn backup format")
            files = manifest["files"]
            names = archive.namelist()
            if len(names) != len(set(names)) or set(names) != {*files, "manifest.json"}:
                raise ValueError("Backup contains duplicate or unlisted entries")
            for name in manifest["directories"]:
                parts = backup_path(name)
                if parts[0] not in {"postgres", "objects"}:
                    raise ValueError("Invalid backup directory")
                staging.joinpath(*parts).mkdir(parents=True, exist_ok=True)
            for name, expected in files.items():
                parts = backup_path(name)
                info = archive.getinfo(name)
                if (
                    stat.S_ISLNK(info.external_attr >> 16)
                    or not isinstance(expected, dict)
                    or expected.get("size") != info.file_size
                    or not isinstance(expected.get("sha256"), str)
                ):
                    raise ValueError("Invalid backup entry")
                target = staging.joinpath(*parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info) as source, target.open("xb") as output:
                    shutil.copyfileobj(source, output)
                if digest_file(target) != expected["sha256"]:
                    raise ValueError("Backup checksum mismatch")
            if (staging / "postgres" / "PG_VERSION").read_text().strip() != "18":
                raise ValueError("Incompatible database backup")
            if not (staging / "settings.json").is_file():
                raise ValueError("Backup has no application settings")
            if (staging / "postgres" / "postmaster.pid").exists():
                raise ValueError("Backup was taken from a running database")
        staging.rename(destination)
    except (zipfile.BadZipFile, KeyError, json.JSONDecodeError) as error:
        raise ValueError("Invalid Cairn backup") from error
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def backup_path(name: str) -> tuple[str, ...]:
    parts = PurePosixPath(name).parts
    if (
        not parts
        or "\\" in name
        or ":" in name
        or name.startswith("/")
        or any(p in (".", "..") or p.endswith((".", " ")) for p in parts)
        or (parts[0] not in {"postgres", "objects"} and name != "settings.json")
    ):
        raise ValueError("Invalid backup path")
    return parts
