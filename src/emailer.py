from __future__ import annotations

import smtplib
from email.message import EmailMessage

from .config import Settings


class EmailNotConfigured(RuntimeError):
    pass


class Emailer:
    def __init__(self, settings: Settings):
        self.settings = settings

    @property
    def configured(self) -> bool:
        return bool(
            self.settings.smtp_host
            and self.settings.smtp_user
            and self.settings.smtp_password
            and self.settings.smtp_from
            and self.settings.smtp_to
        )

    def send(self, subject: str, body: str, recipients: tuple[str, ...] | None = None) -> list[str]:
        if not self.configured:
            raise EmailNotConfigured("SMTP 未配置完整，请检查 .env。")
        to_addrs = recipients or self.settings.smtp_to
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = self.settings.smtp_from
        msg["To"] = ", ".join(to_addrs)
        msg.set_content(body)

        if self.settings.smtp_port == 465:
            with smtplib.SMTP_SSL(self.settings.smtp_host, self.settings.smtp_port, timeout=30) as smtp:
                smtp.login(self.settings.smtp_user, self.settings.smtp_password)
                smtp.send_message(msg)
        else:
            with smtplib.SMTP(self.settings.smtp_host, self.settings.smtp_port, timeout=30) as smtp:
                smtp.starttls()
                smtp.login(self.settings.smtp_user, self.settings.smtp_password)
                smtp.send_message(msg)
        return list(to_addrs)

