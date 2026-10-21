"""Certificate-verifying SMTP delivery without secret or recipient logging."""

import logging
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

    def send_password_reset(self, recipient: str, reset_url: str, expires_at: datetime) -> None: ...

    def send_registration_notice(self, recipient: str) -> None: ...

    def send_password_reset_notice(self, recipient: str) -> None: ...


def account_mail_available(settings: Settings) -> bool:
    return bool(settings.app_url and settings.smtp_host and settings.smtp_from)


def registration_available(settings: Settings) -> bool:
    return bool(settings.registration_enabled and account_mail_available(settings))


class SMTPRegistrationMailSender:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def send_verification(
        self, recipient: str, verification_url: str, expires_at: datetime
    ) -> None:
        settings = self.settings
        if not registration_available(settings):
            raise RegistrationMailUnavailable()
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
        self._send(message)

    def send_password_reset(self, recipient: str, reset_url: str, expires_at: datetime) -> None:
        if not account_mail_available(self.settings):
            raise RegistrationMailUnavailable()
        message = EmailMessage()
        message["From"] = str(self.settings.smtp_from)
        message["To"] = recipient
        message["Subject"] = "重置你的 Cairn 密码"
        message.set_content(
            "请打开下面的链接，设置新密码。打开链接本身不会修改账号。\n"
            "若不是你发起的操作，请忽略此邮件。\n\n"
            f"{reset_url}\n\n"
            f"链接有效至 {expires_at.strftime('%Y-%m-%d %H:%M UTC')}。\n"
        )
        self._send(message)

    def send_registration_notice(self, recipient: str) -> None:
        if not registration_available(self.settings):
            raise RegistrationMailUnavailable()
        message = EmailMessage()
        message["From"] = str(self.settings.smtp_from)
        message["To"] = recipient
        message["Subject"] = "Cairn 账号注册申请"
        message.set_content(
            "有人使用此邮箱申请创建 Cairn 账号。此邮箱已有账号，无需再次注册。\n"
            "若是你本人操作，请返回登录页；忘记密码可使用找回密码。\n"
            "若不是你发起的申请，请忽略此邮件。\n"
        )
        self._send(message)

    def send_password_reset_notice(self, recipient: str) -> None:
        if not account_mail_available(self.settings):
            raise RegistrationMailUnavailable()
        message = EmailMessage()
        message["From"] = str(self.settings.smtp_from)
        message["To"] = recipient
        message["Subject"] = "Cairn 密码找回申请"
        message.set_content(
            "有人使用此邮箱申请找回 Cairn 密码。当前没有可通过密码找回的账号。\n"
            "若你使用第三方账号登录，请通过原登录方式进入。\n"
            "若不是你发起的申请，请忽略此邮件。\n"
        )
        self._send(message)

    def _send(self, message: EmailMessage) -> None:
        settings = self.settings
        assert settings.smtp_host is not None
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
                    logging.getLogger("cairn_api").error("SMTP delivery rejected a recipient")
                    raise RegistrationMailUnavailable()
        except (OSError, smtplib.SMTPException) as exc:
            logging.getLogger("cairn_api").error("SMTP delivery failed (%s)", type(exc).__name__)
            raise RegistrationMailUnavailable() from exc
