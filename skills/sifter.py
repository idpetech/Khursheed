import json
import logging
import os
from email import message_from_bytes
from email.header import decode_header as decode_rfc2047
from email.message import Message
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import imaplib

from skills.base import Skill

logger = logging.getLogger(__name__)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent


@dataclass
class MailAccount:
    name: str
    host: str
    username: str
    password: str


class SifterSkill(Skill):
    name = "sifter"

    def __init__(self, accounts: Optional[List[MailAccount]] = None) -> None:
        if accounts is None:
            self._accounts = self._load_accounts()
        else:
            self._accounts = accounts

    def run(self, task: Dict[str, Any]) -> Dict[str, Any]:
        max_messages = int(task.get("payload", {}).get("max_messages", 50))
        results: List[Dict[str, Any]] = []
        expenses = self._load_expenses()

        for account in self._accounts:
            categorized = self._process_account(account, max_messages)
            results.append({"account": account.name, "categorized": categorized})
            for entry in categorized:
                if entry.get("expense"):
                    expenses.append(entry["expense"])

        self._save_expenses(expenses)
        return {"accounts": results, "expense_count": len(expenses)}

    def _process_account(self, account: MailAccount, max_messages: int) -> List[Dict[str, Any]]:
        categorized: List[Dict[str, Any]] = []
        with imaplib.IMAP4_SSL(account.host) as imap:
            imap.login(account.username, account.password)
            imap.select("INBOX")
            status, data = imap.search(None, "ALL")
            if status != "OK":
                return categorized
            message_ids = data[0].split()
            for msg_id in message_ids[-max_messages:]:
                msg = self._fetch_message(imap, msg_id)
                if msg is None:
                    continue
                subject = self._decode_header(msg.get("Subject", ""))
                sender = self._decode_header(msg.get("From", ""))
                body = self._extract_body(msg)
                category = self._categorize(subject, sender, body)
                expense = self._extract_expense(subject, sender, body)
                categorized.append(
                    {
                        "subject": subject,
                        "from": sender,
                        "category": category,
                        "expense": expense,
                    }
                )
        return categorized

    def _fetch_message(self, imap: imaplib.IMAP4_SSL, msg_id: bytes) -> Optional[Message]:
        status, data = imap.fetch(msg_id, "(RFC822)")
        if status != "OK" or not data or not data[0]:
            return None
        return message_from_bytes(data[0][1])

    def _decode_header(self, value: str) -> str:
        parts = decode_rfc2047(value)
        decoded_parts: list[str] = []
        for data, charset in parts:
            if isinstance(data, bytes):
                decoded_parts.append(data.decode(charset or "utf-8", errors="replace"))
            else:
                decoded_parts.append(data)
        return " ".join(decoded_parts)

    def _extract_body(self, msg: Message) -> str:
        if msg.is_multipart():
            parts = [part for part in msg.walk() if part.get_content_type() == "text/plain"]
        else:
            parts = [msg]
        bodies = []
        for part in parts:
            payload = part.get_payload(decode=True)
            if payload:
                try:
                    bodies.append(payload.decode(part.get_content_charset() or "utf-8", errors="ignore"))
                except LookupError:
                    bodies.append(payload.decode("utf-8", errors="ignore"))
        return "\n".join(bodies).strip()

    def _categorize(self, subject: str, sender: str, body: str) -> str:
        text = f"{subject} {sender} {body}".lower()
        if any(keyword in text for keyword in ["invoice", "payment", "overdue", "bill", "receipt"]):
            return "Urgent/Bill"
        if any(keyword in text for keyword in ["demo", "quote", "proposal", "interest", "pricing"]):
            return "Potential Lead"
        return "General"

    def _extract_expense(self, subject: str, sender: str, body: str) -> Optional[Dict[str, Any]]:
        text = f"{subject} {sender} {body}".lower()
        vendors = {"cursor": "Cursor", "openai": "OpenAI"}
        for key, vendor in vendors.items():
            if key in text and "receipt" in text:
                return {
                    "vendor": vendor,
                    "subject": subject,
                    "source": sender,
                }
        return None

    def _load_expenses(self) -> List[Dict[str, Any]]:
        path = _PROJECT_ROOT / "business_expenses.json"
        if not path.exists():
            return []
        with path.open("r", encoding="utf-8") as file:
            return json.load(file)

    def _save_expenses(self, expenses: List[Dict[str, Any]]) -> None:
        path = _PROJECT_ROOT / "business_expenses.json"
        with path.open("w", encoding="utf-8") as file:
            json.dump(expenses, file, indent=2)

    def _load_accounts(self) -> List[MailAccount]:
        accounts = self._load_accounts_from_config()
        if accounts:
            return accounts
        return self._load_accounts_from_env()

    def _load_accounts_from_config(self) -> List[MailAccount]:
        config_path = _PROJECT_ROOT / "config" / "email_accounts.json"
        if not config_path.exists():
            return []
        data = json.loads(config_path.read_text())
        accounts: List[MailAccount] = []
        for entry in data.get("accounts", []):
            password = entry.get("password")
            if not password and entry.get("password_env"):
                password = os.getenv(entry["password_env"])
            if not password:
                continue
            accounts.append(
                MailAccount(
                    name=entry.get("name", "mail"),
                    host=entry.get("host", ""),
                    username=entry.get("username", ""),
                    password=password,
                )
            )
        return accounts

    def _load_accounts_from_env(self) -> List[MailAccount]:
        accounts: List[MailAccount] = []
        yahoo_email = os.getenv("YAHOO_EMAIL")
        yahoo_password = os.getenv("YAHOO_PASSWORD")
        if yahoo_email and yahoo_password:
            accounts.append(
                MailAccount(
                    name="yahoo",
                    host=os.getenv("YAHOO_IMAP_HOST", "imap.mail.yahoo.com"),
                    username=yahoo_email,
                    password=yahoo_password,
                )
            )
        gmail_email = os.getenv("GMAIL_EMAIL")
        gmail_password = os.getenv("GMAIL_PASSWORD")
        if gmail_email and gmail_password:
            accounts.append(
                MailAccount(
                    name="gmail",
                    host=os.getenv("GMAIL_IMAP_HOST", "imap.gmail.com"),
                    username=gmail_email,
                    password=gmail_password,
                )
            )
        if not accounts:
            logger.warning("No email accounts configured for Sifter skill.")
        return accounts
