"""Offline checks for the opt-in real-tenant Feishu command."""

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "feishu-acceptance.py"
spec = importlib.util.spec_from_file_location("feishu_acceptance", SCRIPT)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
sys.modules["feishu_acceptance"] = module
spec.loader.exec_module(module)


@pytest.mark.parametrize("value, expected", [
    ("https://feishu.cn/docx/Doc123", "Doc123"),
    ("https://team.feishu.cn/docx/Doc123/?copy=1#part", "Doc123"),
    ("http://feishu.cn/docx/Doc123", None),
    ("https://feishu.cn.evil.invalid/docx/Doc123", None),
    ("https://user@feishu.cn/docx/Doc123", None),
    ("https://feishu.cn:8443/docx/Doc123", None),
    ("https://feishu.cn/wiki/Doc123", None),
    ("https://feishu.cn/docx/%44oc123", None),
])
def test_docx_url_is_strict(value: str, expected: str | None) -> None:
    if expected is None:
        with pytest.raises(ValueError):
            module.parse_docx_url(value)
    else:
        assert module.parse_docx_url(value) == expected


def env_file(tmp_path: Path, *, content: str | None = None, mode: int = 0o600) -> Path:
    path = tmp_path / ".env.feishu.local"
    path.write_text(content or (
        "FEISHU_TEST_APP_ID=app-id\n"
        "FEISHU_TEST_APP_SECRET=private-secret\n"
        "FEISHU_TEST_DOCUMENT_URL=https://team.feishu.cn/docx/Doc123\n"
    ))
    path.chmod(mode)
    return path


def args(path: Path, document_id: str = "Doc123") -> list[str]:
    return ["feishu-acceptance.py", "--env-file", str(path),
            "--org-id", "11111111-1111-4111-8111-111111111111",
            "--credential-ref", "team_feishu", "--document-id", document_id]


def test_private_env_file_rejects_world_readability_and_duplicate_keys(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        module.read_env_file(env_file(tmp_path, mode=0o644))
    path = env_file(tmp_path, content=(
        "FEISHU_TEST_APP_ID=a\nFEISHU_TEST_APP_ID=b\n"
        "FEISHU_TEST_APP_SECRET=s\nFEISHU_TEST_DOCUMENT_URL=https://feishu.cn/docx/Doc123\n"
    ))
    with pytest.raises(ValueError):
        module.read_env_file(path)


def test_mismatched_document_is_rejected_before_client_creation(tmp_path: Path, monkeypatch, capsys) -> None:
    created = []
    monkeypatch.setattr(module, "FeishuDocumentClient", lambda **options: created.append(options))
    monkeypatch.setattr(sys, "argv", args(env_file(tmp_path), "OtherDoc"))
    assert module.main() == 2
    assert created == []
    output = capsys.readouterr()
    assert "private-secret" not in output.out + output.err
    assert "Doc123" not in output.out + output.err


def test_success_prints_only_safe_digest_and_timing(tmp_path: Path, monkeypatch, capsys) -> None:
    seen = []

    class Client:
        def __init__(self, **options):
            seen.append(options)

        def read_document(self, document_id):
            seen.append(document_id)
            return SimpleNamespace(revision_id=7, content_sha256="a" * 64,
                                   title="private-title", content="private-document")

    monkeypatch.setattr(module, "FeishuDocumentClient", Client)
    monkeypatch.setattr(sys, "argv", args(env_file(tmp_path)))
    assert module.main() == 0
    output = capsys.readouterr().out
    assert "read: ok" in output and "revision=7" in output and "content_sha256=" in output
    assert "private-secret" not in output and "private-title" not in output
    assert "private-document" not in output and "Doc123" not in output
    assert seen[0]["timeout_seconds"] == 10.0
    assert seen[1] == "Doc123"
