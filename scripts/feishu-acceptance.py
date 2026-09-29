#!/usr/bin/env python3
"""Opt-in, read-only Feishu tenant check. Never prints credentials or document text."""

from __future__ import annotations

import argparse
import re
import stat
import sys
from pathlib import Path
from time import monotonic
from urllib.parse import urlsplit
from uuid import UUID

WORKER_SRC = Path(__file__).resolve().parents[1] / "apps" / "worker" / "src"
sys.path.insert(0, str(WORKER_SRC))

from cairn_worker.feishu import FeishuDocumentClient, FeishuFailure

_DOCUMENT_ID = re.compile(r"[A-Za-z0-9]{1,128}\Z", re.ASCII)
_ALIAS = re.compile(r"[A-Za-z][A-Za-z0-9_-]{0,63}\Z", re.ASCII)
_HOST = re.compile(r"(?:[a-z0-9-]+\.)*feishu\.cn\Z", re.ASCII)
_KEYS = frozenset({"FEISHU_TEST_APP_ID", "FEISHU_TEST_APP_SECRET", "FEISHU_TEST_DOCUMENT_URL"})


def parse_docx_url(value: str) -> str:
    try:
        parts = urlsplit(value)
        port = parts.port
    except ValueError as exc:
        raise ValueError("invalid docx URL") from exc
    if (
        parts.scheme != "https" or not parts.hostname or not _HOST.fullmatch(parts.hostname)
        or parts.username is not None or parts.password is not None or port is not None
        or parts.path.count("/") not in (2, 3)
    ):
        raise ValueError("invalid docx URL")
    path = parts.path.removesuffix("/")
    if not path.startswith("/docx/"):
        raise ValueError("invalid docx URL")
    document_id = path[len("/docx/"):]
    if not _DOCUMENT_ID.fullmatch(document_id):
        raise ValueError("invalid docx URL")
    return document_id


def read_env_file(path: Path) -> dict[str, str]:
    if path.is_symlink():
        raise ValueError("env file must be a regular private file")
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077 or info.st_size > 16 * 1024:
        raise ValueError("env file must be regular, at most 16 KiB, and mode 0600")
    result: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError("invalid env file format")
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if key not in _KEYS:
            continue
        if key in result:
            raise ValueError("duplicate env key")
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        if not value or len(value) > 4096 or any(ord(char) < 32 or ord(char) == 127 for char in value):
            raise ValueError("required env value is empty or invalid")
        result[key] = value
    if result.keys() != _KEYS:
        raise ValueError("required env values are missing")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Read one Feishu docx document without displaying its content")
    parser.add_argument("--env-file", required=True, type=Path)
    parser.add_argument("--org-id", required=True)
    parser.add_argument("--credential-ref", required=True)
    parser.add_argument("--document-id", required=True)
    args = parser.parse_args()
    try:
        UUID(args.org_id)
        if not _ALIAS.fullmatch(args.credential_ref) or not _DOCUMENT_ID.fullmatch(args.document_id):
            raise ValueError("invalid scoped identifier")
        values = read_env_file(args.env_file)
        if parse_docx_url(values["FEISHU_TEST_DOCUMENT_URL"]) != args.document_id:
            raise ValueError("document URL and ID differ")
    except (OSError, UnicodeError, ValueError):
        print("validation: failed; check private env file, organization, alias and docx ID", file=sys.stderr)
        return 2

    started = monotonic()
    try:
        snapshot = FeishuDocumentClient(
            app_id=values["FEISHU_TEST_APP_ID"],
            app_secret=values["FEISHU_TEST_APP_SECRET"],
            timeout_seconds=10.0,
            maximum_response_bytes=2 * 1024 * 1024,
        ).read_document(args.document_id)
    except FeishuFailure as failure:
        print(f"read: failed; code={failure.code}; elapsed_ms={int((monotonic() - started) * 1000)}")
        return 1
    except Exception:  # noqa: BLE001 -- do not print exception text that may contain secrets
        print(f"read: failed; code=unexpected; elapsed_ms={int((monotonic() - started) * 1000)}")
        return 1
    print(f"read: ok; elapsed_ms={int((monotonic() - started) * 1000)}; "
          f"revision={snapshot.revision_id}; content_sha256={snapshot.content_sha256}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
