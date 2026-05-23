from __future__ import annotations

import smtplib
import ssl
from abc import ABC, abstractmethod
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import certifi


class Notifier(ABC):
    @abstractmethod
    def send(self, content: str) -> str:
        raise NotImplementedError


class MarkdownFileNotifier(Notifier):
    def __init__(self, path: str = "executive_summary.md") -> None:
        self._path = Path(path)

    def send(self, content: str) -> str:
        self._path.write_text(content)
        return str(self._path)


class EmailNotifier(Notifier):
    def __init__(
        self,
        sender: str,
        password: str,
        recipient: str,
        subject: str = "Khursheed Executive Summary",
        smtp_host: str = "smtp.gmail.com",
        smtp_port: int = 587,
    ) -> None:
        self._sender = sender
        self._password = password
        self._recipient = recipient
        self._subject = subject
        self._smtp_host = smtp_host
        self._smtp_port = smtp_port

    def send(self, content: str) -> str:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = self._subject
        msg["From"] = self._sender
        msg["To"] = self._recipient
        msg.attach(MIMEText(content, "plain"))
        ssl_ctx = ssl.create_default_context(cafile=certifi.where())
        with smtplib.SMTP(self._smtp_host, self._smtp_port) as server:
            server.ehlo()
            server.starttls(context=ssl_ctx)
            server.ehlo()
            server.login(self._sender, self._password)
            server.sendmail(self._sender, self._recipient, msg.as_string())
        return f"Email sent to {self._recipient}"


class CompositeNotifier(Notifier):
    """Sends to multiple notifiers at once."""

    def __init__(self, *notifiers: Notifier) -> None:
        self._notifiers = notifiers

    def send(self, content: str) -> str:
        results = [n.send(content) for n in self._notifiers]
        return ", ".join(results)
