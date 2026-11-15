from __future__ import annotations

import json
import os
import smtplib
import ssl
import urllib.error
import urllib.request
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


def _telegram_chunks(content: str, limit: int = 3500) -> list[str]:
    text = content.strip() or "—"
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    current = ""
    for line in text.splitlines(keepends=True):
        if len(line) > limit:
            if current:
                chunks.append(current.rstrip())
                current = ""
            for start in range(0, len(line), limit):
                chunks.append(line[start : start + limit])
            continue
        if len(current) + len(line) > limit:
            chunks.append(current.rstrip())
            current = line
        else:
            current += line
    if current.strip():
        chunks.append(current.rstrip())
    return chunks or ["—"]


class TelegramNotifier(Notifier):
    """Send the daily brief to a Telegram bot. Missing config is skipped, not fatal."""

    def send(self, content: str) -> str:
        import logging

        token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
        chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
        if not token or not chat_id:
            logging.getLogger(__name__).warning(
                "Telegram configuration incomplete; daily brief not sent"
            )
            return "Telegram skipped (missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID)"
        if content.lstrip().startswith("# Executive Summary"):
            from executive_summary import mobile_update

            content = mobile_update(content)
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        chunks = _telegram_chunks(content)
        try:
            for index, chunk in enumerate(chunks, start=1):
                text = chunk if len(chunks) == 1 else f"({index}/{len(chunks)})\n{chunk}"
                body = json.dumps(
                    {
                        "chat_id": chat_id,
                        "text": text[:4096],
                        "disable_web_page_preview": True,
                    }
                ).encode("utf-8")
                request = urllib.request.Request(
                    url,
                    data=body,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                ssl_ctx = ssl.create_default_context(cafile=certifi.where())
                with urllib.request.urlopen(request, timeout=20, context=ssl_ctx) as response:
                    if response.status >= 400:
                        raise RuntimeError(f"Telegram API returned HTTP {response.status}")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:200]
            logging.getLogger(__name__).warning("Telegram send failed: HTTP %s %s", exc.code, detail)
            return f"Telegram failed: HTTP {exc.code}"
        except Exception as exc:
            logging.getLogger(__name__).warning("Telegram send failed: %s", exc)
            return f"Telegram failed: {exc}"
        return f"Telegram sent to {chat_id}"


def daily_brief_notifier(summary_path: str | None = None) -> Notifier:
    """Write the brief to disk and send it to Telegram when the bot is configured."""
    return CompositeNotifier(
        MarkdownFileNotifier(summary_path or "executive_summary.md"),
        TelegramNotifier(),
    )


def _whatsapp_param(value: str) -> str:
    """Template parameters reject newlines, tabs, and empty text."""
    cleaned = " ".join(str(value).split())
    if not cleaned:
        return "—"
    return cleaned[:1024]


def send_whatsapp_template(title: str, detail: str) -> str:
    """Send a pre-approved utility template. Raises if config or the API call fails."""
    token = os.getenv("WHATSAPP_ACCESS_TOKEN", "").strip()
    phone_number_id = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "").strip()
    recipient = os.getenv("WHATSAPP_TO", "").strip()
    template = os.getenv("WHATSAPP_TEMPLATE_NAME", "").strip()
    language = os.getenv("WHATSAPP_TEMPLATE_LANG", "en").strip() or "en"
    if not all([token, phone_number_id, recipient, template]):
        raise RuntimeError("WhatsApp configuration incomplete (missing env vars)")

    to_digits = "".join(ch for ch in recipient if ch.isdigit())
    if not to_digits:
        raise RuntimeError("WhatsApp recipient has no digits")
    body = {
        "messaging_product": "whatsapp",
        "to": to_digits,
        "type": "template",
        "template": {
            "name": template,
            "language": {"code": language},
            "components": [
                {
                    "type": "body",
                    "parameters": [
                        {"type": "text", "text": _whatsapp_param(title)},
                        {"type": "text", "text": _whatsapp_param(detail)},
                    ],
                }
            ],
        },
    }
    request = urllib.request.Request(
        f"https://graph.facebook.com/v21.0/{phone_number_id}/messages",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            if response.status >= 400:
                raise RuntimeError(f"WhatsApp API returned HTTP {response.status}")
    except urllib.error.HTTPError as exc:
        detail_text = exc.read().decode("utf-8", errors="replace")[:300]
        raise RuntimeError(f"WhatsApp API returned HTTP {exc.code}: {detail_text}") from exc
    return f"WhatsApp sent to {to_digits}"


class CompositeNotifier(Notifier):
    """Sends to multiple notifiers at once."""

    def __init__(self, *notifiers: Notifier) -> None:
        self._notifiers = notifiers

    def send(self, content: str) -> str:
        results = [n.send(content) for n in self._notifiers]
        return ", ".join(results)
