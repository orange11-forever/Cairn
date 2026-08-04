import base64

from cairn_api.auth.security import (
    DUMMY_PASSWORD_HASH,
    derive_csrf_token,
    digest_token,
    hash_password,
    issue_session_material,
    normalize_email,
    verify_csrf_token,
    verify_password,
)


def test_normalize_email_strips_and_casefolds() -> None:
    assert normalize_email("  Demo@CAIRN.DEV  ") == "demo@cairn.dev"


def test_password_hash_uses_argon2id_and_verifies_only_matching_password() -> None:
    digest = hash_password("correct horse battery staple")

    assert digest.startswith("$argon2id$")
    assert verify_password("correct horse battery staple", digest) is True
    assert verify_password("wrong", digest) is False


def test_dummy_password_hash_is_precomputed_argon2id() -> None:
    assert DUMMY_PASSWORD_HASH.startswith("$argon2id$")


def test_session_material_uses_distinct_raw_values_and_only_exposes_digests_for_storage() -> None:
    material = issue_session_material(b"x" * 32)

    assert len(base64.urlsafe_b64decode(material.session_token + "==")) == 32
    assert material.csrf_token != material.session_token
    assert digest_token(material.session_token) == material.session_digest
    assert derive_csrf_token(material.session_token, b"x" * 32) == material.csrf_token
    assert digest_token(material.csrf_token) == material.csrf_digest


def test_csrf_verification_rejects_wrong_or_tampered_values() -> None:
    material = issue_session_material(b"x" * 32)

    assert verify_csrf_token(material.session_token, material.csrf_token, b"x" * 32) is True
    assert verify_csrf_token(material.session_token, "wrong", b"x" * 32) is False
    assert verify_csrf_token(material.session_token, material.csrf_token, b"y" * 32) is False
