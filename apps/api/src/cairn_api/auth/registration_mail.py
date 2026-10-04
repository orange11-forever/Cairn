"""Certificate-verifying SMTP delivery without secret or recipient logging."""

import smtplib
import ssl
from datetime import datetime
from email.message import EmailMessage
from typing import Protocol

from cairn_api.settings import Settings


class RegistrationMailUnavailable(Exception):
    """The transport did not confirm acceptance; details must never reach the client."""


class RegistrationMailSender(Protocol):
    def send_verification(
        self, recipient: str, verification_url: str, expires_at: datetime
    ) -> None: ...


def registration_available(settings: Settings) -> bool:
    return bool(
        settings.registration_enabled
        and settings.app_url
        and settings.smtp_host
        and settings.smtp_from
    )


class SMTPRegistrationMailSender:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def send_verification(
        self, recipient: str, verification_url: str, expires_at: datetime
    ) -> None:
        settings = self.settings
        if not registration_available(settings):
            raise RegistrationMailUnavailable()
        assert settings.smtp_host is not None
        message = EmailMessage()
        message["From"] = str(settings.smtp_from)
        message["To"] = recipient
        message["Subject"] = "验证你的 Cairn 邮箱"
        message.set_content(
            "请打开下面的链接，输入你注册时设置的密码并确认，才能创建账号。\n"
            "若不是你发起的注册，请忽略此邮件。\n\n"
            f"{verification_url}\n\n"
            f"链接有效至 {expires_at.strftime('%Y-%m-%d %H:%M UTC')}。Cairn 不会自动登录。\n"
        )
        context = ssl.create_default_context()
        try:
            if settings.smtp_security == "tls":
                transport = smtplib.SMTP_SSL(
                    settings.smtp_host, settings.smtp_port, timeout=10, context=context
                )
            else:
                transport = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10)
            with transport:
                transport.ehlo()
                if settings.smtp_security == "starttls":
                    transport.starttls(context=context)
                    transport.ehlo()
                if settings.smtp_username and settings.smtp_password:
                    transport.login(
                        settings.smtp_username, settings.smtp_password.get_secret_value()
                    )
                if transport.send_message(message):
                    raise RegistrationMailUnavailable()
        except (OSError, smtplib.SMTPException) as exc:
            raise RegistrationMailUnavailable() from exc
