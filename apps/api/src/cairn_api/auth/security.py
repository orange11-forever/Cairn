import base64
import hashlib
import hmac
import secrets
from dataclasses import dataclass

from pwdlib import PasswordHash
from pwdlib.hashers.argon2 import Argon2Hasher

_PASSWORD_HASH = PasswordHash((Argon2Hasher(),))
DUMMY_PASSWORD_HASH = _PASSWORD_HASH.hash(
    "cairn-dummy-password-for-constant-time-verification"
)


@dataclass(frozen=True)
class SessionMaterial:
    session_token: str
    session_digest: bytes
    csrf_token: str
    csrf_digest: bytes


def normalize_email(value: str) -> str:
    return value.strip().casefold()


def hash_password(password: str) -> str:
    return _PASSWORD_HASH.hash(password)


def verify_password(password: str, digest: str) -> bool:
    return _PASSWORD_HASH.verify(password, digest)


def digest_token(value: str) -> bytes:
    return hashlib.sha256(value.encode("ascii")).digest()


def derive_csrf_token(session_token: str, csrf_secret: bytes) -> str:
    digest = hmac.digest(csrf_secret, session_token.encode("ascii"), "sha256")
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def verify_csrf_token(session_token: str, csrf_token: str, csrf_secret: bytes) -> bool:
    expected = derive_csrf_token(session_token, csrf_secret)
    return hmac.compare_digest(expected, csrf_token)


def issue_session_material(csrf_secret: bytes) -> SessionMaterial:
    session_token = secrets.token_urlsafe(32)
    csrf_token = derive_csrf_token(session_token, csrf_secret)
    return SessionMaterial(
        session_token=session_token,
        session_digest=digest_token(session_token),
        csrf_token=csrf_token,
        csrf_digest=digest_token(csrf_token),
    )
