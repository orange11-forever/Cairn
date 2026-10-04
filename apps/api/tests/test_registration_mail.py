import smtplib
import ssl
from collections.abc import Generator
from datetime import UTC, datetime
from email import policy
from email.parser import BytesParser
from socketserver import StreamRequestHandler, ThreadingTCPServer
from threading import Thread
from typing import cast
from unittest.mock import MagicMock

import pytest
from cairn_api.auth.registration_mail import (
    RegistrationMailUnavailable,
    SMTPRegistrationMailSender,
    registration_available,
)
from cairn_api.settings import Settings
from pydantic import ValidationError


class MailCapture(ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self) -> None:
        self.messages: list[bytes] = []
        super().__init__(("127.0.0.1", 0), CaptureHandler)


class CaptureHandler(StreamRequestHandler):
    def handle(self) -> None:
        self.wfile.write(b"220 localhost capture\r\n")
        while line := self.rfile.readline():
            command = line.split(b" ", 1)[0].strip().upper()
            if command == b"DATA":
                self.wfile.write(b"354 send message\r\n")
                parts: list[bytes] = []
                while (part := self.rfile.readline()) not in (b".\r\n", b""):
                    parts.append(part.removeprefix(b".") if part.startswith(b"..") else part)
                cast(MailCapture, self.server).messages.append(b"".join(parts))
                self.wfile.write(b"250 captured\r\n")
            elif command == b"QUIT":
                self.wfile.write(b"221 goodbye\r\n")
                return
            else:
                self.wfile.write(b"250 localhost\r\n")


@pytest.fixture()
def capture() -> Generator[MailCapture, None, None]:
    with MailCapture() as server:
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield server
        finally:
            server.shutdown()
            thread.join(timeout=2)


def settings(**kwargs: object) -> Settings:
    return Settings(
        environment="test",
        app_url="http://localhost:5500",
        registration_enabled=True,
        smtp_host="127.0.0.1",
        smtp_security="plain",
        smtp_from="cairn@example.com",
        _env_file=None,  # pyright: ignore[reportCallIssue]
        **kwargs,
    )  # type: ignore[arg-type] # pyright: ignore[reportCallIssue]


def test_real_loopback_smtp_message_preserves_fragment_and_never_includes_password(
    capture: MailCapture,
) -> None:
    sender = SMTPRegistrationMailSender(settings(smtp_port=capture.server_address[1]))
    url = "http://localhost:5500/register/verify#token=test-proof"
    sender.send_verification("person@example.com", url, datetime(2026, 10, 3, 16, 0, tzinfo=UTC))
    assert len(capture.messages) == 1
    message = BytesParser(policy=policy.default).parsebytes(capture.messages[0])
    assert message["To"] == "person@example.com"
    assert message["From"] == "cairn@example.com"
    assert "Cairn" in str(message["Subject"])
    content = cast(bytes, message.get_payload(decode=True)).decode("utf-8")
    assert url in content
    assert "2026-10-03 16:00 UTC" in content
    assert "注册时设置的密码" in content and "请忽略此邮件" in content


@pytest.mark.parametrize("mode", ["starttls", "tls"])
def test_transport_requires_verified_tls_authentication_and_ten_second_timeout(
    monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    config = Settings(
        environment="test",
        app_url="http://localhost:5500",
        registration_enabled=True,
        smtp_host="mail.example.com",
        smtp_security=mode,
        smtp_from="cairn@example.com",
        smtp_username="smtp-user",
        smtp_password="test-secret",
        _env_file=None,  # pyright: ignore[reportCallIssue]
    )  # pyright: ignore[reportCallIssue,reportArgumentType]
    transport = MagicMock()
    transport.__enter__.return_value = transport
    transport.send_message.return_value = {}
    constructor = MagicMock(return_value=transport)
    monkeypatch.setattr(smtplib, "SMTP_SSL" if mode == "tls" else "SMTP", constructor)
    SMTPRegistrationMailSender(config).send_verification(
        "person@example.com", "http://localhost:5500/register/verify#token=test", datetime.now(UTC)
    )
    assert constructor.call_args.kwargs["timeout"] == 10
    context = (
        constructor.call_args.kwargs["context"]
        if mode == "tls"
        else transport.starttls.call_args.kwargs["context"]
    )
    assert context.verify_mode == ssl.CERT_REQUIRED and context.check_hostname is True
    transport.login.assert_called_once_with("smtp-user", "test-secret")
    assert transport.ehlo.call_count == (2 if mode == "starttls" else 1)


@pytest.mark.parametrize(
    "failure",
    [
        TimeoutError("hidden"),
        smtplib.SMTPRecipientsRefused({"person@example.com": (550, b"hidden")}),
        smtplib.SMTPAuthenticationError(535, b"hidden"),
    ],
)
def test_transport_failure_is_typed_without_unsafe_detail(
    monkeypatch: pytest.MonkeyPatch, failure: Exception
) -> None:
    monkeypatch.setattr(smtplib, "SMTP", MagicMock(side_effect=failure))
    with pytest.raises(RegistrationMailUnavailable) as error:
        SMTPRegistrationMailSender(settings()).send_verification(
            "person@example.com",
            "http://localhost:5500/register/verify#token=test",
            datetime.now(UTC),
        )
    assert str(error.value) == ""


def test_header_injection_is_rejected_before_transport(monkeypatch: pytest.MonkeyPatch) -> None:
    transport = MagicMock()
    monkeypatch.setattr(smtplib, "SMTP", transport)
    with pytest.raises(ValueError):
        SMTPRegistrationMailSender(settings()).send_verification(
            "person@example.com\r\nBcc: attacker@example.com",
            "http://localhost:5500/register/verify#token=test",
            datetime.now(UTC),
        )
    transport.assert_not_called()


@pytest.mark.parametrize(
    "environment,host",
    [
        ("production", "127.0.0.1"),
        ("development", "localhost"),
        ("test", "mail.example.com"),
        ("test", "127.0.0.1.evil.example"),
    ],
)
def test_plaintext_smtp_requires_explicit_test_and_loopback(environment: str, host: str) -> None:
    with pytest.raises(ValidationError, match="plaintext SMTP"):
        Settings(environment=environment, smtp_host=host, smtp_security="plain", _env_file=None)  # pyright: ignore[reportCallIssue,reportArgumentType]


def test_missing_mail_defaults_registration_off_and_enabled_tls_requires_auth() -> None:
    assert not registration_available(Settings(_env_file=None))  # pyright: ignore[reportCallIssue]
    assert not registration_available(Settings(registration_enabled=True, _env_file=None))  # pyright: ignore[reportCallIssue]
    with pytest.raises(ValidationError, match="authentication"):
        Settings(
            registration_enabled=True,
            app_url="http://localhost:5500",
            smtp_host="mail.example.com",
            smtp_from="cairn@example.com",
            _env_file=None,  # pyright: ignore[reportCallIssue]
        )  # pyright: ignore[reportCallIssue,reportArgumentType]
