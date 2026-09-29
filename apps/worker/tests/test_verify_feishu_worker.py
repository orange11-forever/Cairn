"""Guard the browser verification transport against real-tenant use."""

import importlib.util
from pathlib import Path
from uuid import UUID

import pytest
from cairn_worker.feishu import FeishuFailure

SUPPORT = Path(__file__).resolve().parent / "support" / "verify_feishu_worker.py"
spec = importlib.util.spec_from_file_location("verify_feishu_worker", SUPPORT)
assert spec and spec.loader
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)


def safe_environment() -> dict[str, str]:
    return {
        "CAIRN_ENVIRONMENT": "test",
        "CAIRN_VERIFY_FAKE_FEISHU": "1",
        "CAIRN_FEISHU_CREDENTIALS_JSON": "{}",
        "DATABASE_URL": "postgresql+psycopg://cairn:cairn-local-only@127.0.0.1:55442/cairn_test",
    }


@pytest.mark.parametrize("key, value", [
    ("CAIRN_ENVIRONMENT", "production"),
    ("CAIRN_VERIFY_FAKE_FEISHU", "0"),
    ("CAIRN_FEISHU_CREDENTIALS_JSON", '{"real":"credentials"}'),
    ("DATABASE_URL", "postgresql+psycopg://cairn:pass@127.0.0.1:5432/cairn"),
    ("DATABASE_URL", "postgresql+psycopg://cairn:pass@remote:5432/cairn_test"),
    ("FEISHU_TEST_APP_ID", "real-app"),
])
def test_fake_worker_rejects_nonverification_environment(key: str, value: str) -> None:
    environment = safe_environment()
    environment[key] = value
    with pytest.raises(RuntimeError):
        fixture.validate_environment(environment)


def test_fake_reader_accepts_exact_fixture_and_never_contacts_network() -> None:
    fixture.validate_environment(safe_environment())
    client = fixture.FixtureResolver().create_client(
        org_id=fixture.FIXTURE_ORG, credential_ref=fixture.FIXTURE_ALIAS,
    )
    snapshot = client.read_document(fixture.FIXTURE_DOCUMENT_ID)
    assert snapshot.document_id == fixture.FIXTURE_DOCUMENT_ID
    assert fixture.FIXTURE_PHRASE in snapshot.content
    assert snapshot.revision_id == 1
    assert len(snapshot.content_sha256) == 64
    with pytest.raises(FeishuFailure, match="feishu_unavailable"):
        client.read_document("OtherDocument")
    with pytest.raises(OSError):
        fixture.FixtureResolver().create_client(
            org_id=UUID("00000000-0000-4000-8000-000000002002"),
            credential_ref=fixture.FIXTURE_ALIAS,
        )
