import json
import logging
import os
import hashlib
import re
from email import message_from_bytes
from email.header import decode_header as decode_rfc2047
from email.message import Message
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import imaplib
from datetime import datetime, timedelta, timezone

from skills.base import Skill
from runtime import resolve_db_path

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
        lookback_days = self._lookback_days(task)
        results: List[Dict[str, Any]] = []
        expenses = self._load_expenses()
        priority_actions: List[Dict[str, Any]] = []
        findings: List[Dict[str, Any]] = []
        ignored: List[str] = []
        coverage_accounts: List[Dict[str, Any]] = []
        envelopes = 0
        unique = 0
        opened = 0
        unavailable = 0
        # Bills already saved are re-ranked from their due date. This does not
        # open a mailbox, so it ignores the mail lookback setting.
        try:
            from priority_inbox import refresh_open_bill_priorities

            refresh_open_bill_priorities(str(resolve_db_path("khursheed.db")))
        except Exception as exc:
            logger.warning("Could not refresh stored bill priorities: %s", exc)

        for account in self._accounts:
            account_result = self._process_account(account, max_messages, lookback_days)
            categorized = account_result["categorized"]
            results.append({"account": account.name, "categorized": categorized})
            priority_actions.extend(account_result["priority_actions"])
            findings.extend(account_result["findings"])
            ignored.extend(account_result["ignored"])
            coverage_accounts.append(account_result["coverage"])
            envelopes += account_result["envelopes"]
            unique += account_result["unique"]
            opened += account_result["opened"]
            unavailable += account_result["unavailable"]
            for entry in categorized:
                if entry.get("expense"):
                    expenses.append(entry["expense"])

        self._save_expenses(expenses)
        from skills.mail_scan import format_scan_report

        scan = {
            "coverage": {
                "accounts": coverage_accounts,
                "envelopes": envelopes,
                "unique": unique,
                "opened": opened,
                "unavailable": unavailable,
            },
            "findings": findings,
            "ignored": ignored[:8],
        }
        scan["report"] = format_scan_report(scan["coverage"], findings, scan["ignored"])
        return {
            "accounts": results,
            "expense_count": len(expenses),
            "priority_actions": priority_actions,
            "scan": scan,
            "scan_report": scan["report"],
        }

    def _lookback_days(self, task: Dict[str, Any]) -> int:
        raw = task.get("payload", {}).get("lookback_days")
        if raw is None:
            try:
                from desk_settings import mail_lookback_days

                return mail_lookback_days(resolve_db_path("khursheed.db"))
            except Exception as exc:
                logger.warning("Mail lookback setting unavailable: %s", exc)
                return 2
        try:
            days = int(raw)
        except (TypeError, ValueError):
            days = 2
        return max(1, min(days, 30))

    def _process_account(
        self,
        account: MailAccount,
        max_messages: int,
        lookback_days: int,
    ) -> Dict[str, Any]:
        """Review headers in the bill folders, then open only the interesting mail."""
        from skills.mail_scan import choose_mailboxes
        from skills.mail_scan import local_screen
        from skills.mail_scan import notable_ignore
        from skills.mail_scan import parse_mailbox_name
        from skills.mail_scan import short_when
        from skills.mail_scan import vendor_name

        categorized: List[Dict[str, Any]] = []
        priority_actions: List[Dict[str, Any]] = []
        findings: List[Dict[str, Any]] = []
        ignored: List[str] = []
        coverage = {"name": account.name, "mailboxes": [], "failed": [], "error": ""}
        envelopes = 0
        opened = 0
        unavailable = 0
        seen: Dict[str, Dict[str, str]] = {}
        since_date = (datetime.now(timezone.utc) - timedelta(days=lookback_days)).strftime("%d-%b-%Y")
        body_cap = max(1, max_messages)

        try:
            with imaplib.IMAP4_SSL(account.host) as imap:
                imap.login(account.username, account.password)
                mailboxes = choose_mailboxes(self._list_mailbox_names(imap, parse_mailbox_name))
                if not mailboxes:
                    mailboxes = ["INBOX"]
                for mailbox in mailboxes:
                    try:
                        status, _data = imap.select(mailbox, readonly=True)
                        if status != "OK":
                            unavailable += 1
                            coverage["failed"].append(mailbox)
                            continue
                        coverage["mailboxes"].append(mailbox)
                        status, data = imap.search(None, "SINCE", since_date)
                        if status != "OK" or not data or not data[0]:
                            continue
                        message_ids = data[0].split()[:2000]
                        envelopes += len(message_ids)
                        for header in self._fetch_headers(imap, message_ids):
                            header["mailbox"] = mailbox
                            key = header.get("message_id") or f"{mailbox}:{header.get('uid')}"
                            if key and key not in seen:
                                seen[key] = header
                    except Exception as exc:
                        unavailable += 1
                        coverage["failed"].append(mailbox)
                        logger.warning("Mailbox %s on %s failed: %s", mailbox, account.name, exc)
                interesting = []
                for header in seen.values():
                    subject = header.get("subject") or ""
                    if notable_ignore(subject) and len(ignored) < 8:
                        ignored.append(subject)
                    bucket = local_screen(subject, header.get("from") or "")
                    if bucket:
                        header["bucket"] = bucket
                        interesting.append(header)
                interesting.sort(key=lambda item: ("upcoming_bill", "renewal", "statement", "subscription").index(item["bucket"]))
                for header in interesting[:body_cap]:
                    opened += 1
                    self._open_interesting(
                        imap,
                        account,
                        header,
                        categorized,
                        priority_actions,
                        findings,
                        short_when,
                        vendor_name,
                    )
        except Exception as exc:
            coverage["error"] = str(exc)
            unavailable += 1
            logger.error("Error connecting to account %s: %s", account.name, exc)

        return {
            "categorized": categorized,
            "priority_actions": priority_actions,
            "findings": findings,
            "ignored": ignored,
            "coverage": coverage,
            "envelopes": envelopes,
            "unique": len(seen),
            "opened": opened,
            "unavailable": unavailable,
        }

    def _list_mailbox_names(self, imap: imaplib.IMAP4_SSL, parse_name) -> List[str]:
        status, data = imap.list()
        if status != "OK" or not data:
            return []
        names = []
        for row in data:
            if not row:
                continue
            text = row.decode("utf-8", errors="replace") if isinstance(row, bytes) else str(row)
            name = parse_name(text)
            if name:
                names.append(name)
        return names

    def _fetch_headers(self, imap: imaplib.IMAP4_SSL, message_ids: List[bytes]) -> List[Dict[str, str]]:
        headers: List[Dict[str, str]] = []
        for start in range(0, len(message_ids), 40):
            chunk = message_ids[start : start + 40]
            query = b",".join(chunk)
            status, data = imap.fetch(query, "(BODY.PEEK[HEADER.FIELDS (SUBJECT FROM DATE MESSAGE-ID)])")
            if status != "OK" or not data:
                continue
            for item in data:
                raw = item[1] if isinstance(item, tuple) and len(item) > 1 else None
                if not isinstance(raw, (bytes, bytearray)):
                    continue
                msg = message_from_bytes(raw)
                headers.append(
                    {
                        "uid": self._uid_from_fetch(item, chunk),
                        "subject": self._decode_header(msg.get("Subject", "")),
                        "from": self._decode_header(msg.get("From", "")),
                        "date": self._decode_header(msg.get("Date") or ""),
                        "message_id": self._decode_header(msg.get("Message-ID") or ""),
                    }
                )
        return headers

    @staticmethod
    def _uid_from_fetch(item, chunk: List[bytes]) -> str:
        prefix = item[0] if isinstance(item, tuple) else item
        if isinstance(prefix, bytes):
            token = prefix.split(b" ", 1)[0]
            if token.isdigit():
                return token.decode()
        return chunk[0].decode(errors="replace") if chunk else ""

    def _open_interesting(
        self,
        imap: imaplib.IMAP4_SSL,
        account: MailAccount,
        header: Dict[str, str],
        categorized: List[Dict[str, Any]],
        priority_actions: List[Dict[str, Any]],
        findings: List[Dict[str, Any]],
        short_when,
        vendor_name,
    ) -> None:
        bucket = header.get("bucket") or ""
        subject = header.get("subject") or ""
        sender = header.get("from") or ""
        sent_at = header.get("date") or ""
        message_id = header.get("message_id") or f"unknown-{header.get('uid')}"
        body = ""
        uid = header.get("uid") or ""
        if uid.isdigit():
            mailbox = header.get("mailbox") or "INBOX"
            imap.select(mailbox, readonly=True)
            msg = self._fetch_message(imap, uid.encode())
            if msg is not None:
                body = self._extract_body(msg)
                subject = self._decode_header(msg.get("Subject", "")) or subject
                sender = self._decode_header(msg.get("From", "")) or sender
                sent_at = self._decode_header(msg.get("Date") or "") or sent_at
                message_id = self._decode_header(msg.get("Message-ID") or "") or message_id
        note = subject
        if not body:
            note = f"{subject} (body not retrievable; no amount or due date)"
        if body and bucket in {"upcoming_bill", "statement"}:
            detection = self._detect_financial_urgency(
                subject,
                sender,
                body,
                message_id,
                account.name,
                sent_at,
                account.username,
                forced_kind="new_bill",
            )
            if detection:
                priority_actions.append(detection)
        if bucket in {"renewal", "statement", "subscription"}:
            notice_id = self._queue_notice(
                account, bucket, subject, sender, message_id, sent_at, note
            )
            if notice_id:
                priority_actions.append(
                    {
                        "action_id": notice_id,
                        "kind": "renewal_notice" if bucket == "renewal" else "mail_notice",
                        "priority": 2 if bucket == "renewal" else 1,
                    }
                )
        when = short_when(sent_at)
        vendor = vendor_name(sender)
        prefix = f"{when} — " if when else ""
        findings.append(
            {
                "bucket": bucket,
                "account": account.name,
                "subject": subject,
                "line": f"{prefix}{vendor} ({account.name}): {note}",
            }
        )
        if body:
            categorized.append(
                {
                    "subject": subject,
                    "from": sender,
                    "date": sent_at,
                    "category": self._categorize(subject, sender, body),
                    "expense": self._extract_expense(subject, sender, body),
                }
            )

    def _queue_notice(
        self,
        account: MailAccount,
        bucket: str,
        subject: str,
        sender: str,
        message_id: str,
        sent_at: str,
        note: str,
    ) -> str | None:
        """A statement, subscription, or deactivation can be closed from Today."""
        try:
            from skills.mail_scan import queue_mail_notice

            return queue_mail_notice(
                str(resolve_db_path("khursheed.db")),
                bucket=bucket,
                account=account.name,
                subject=subject,
                sender=sender,
                line=note,
                message_id=message_id,
                sent_at=sent_at,
            )
        except Exception as exc:
            logger.warning("Mail notice could not be queued: %s", exc)
            return None

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
        plain_parts: list[str] = []
        html_parts: list[str] = []
        parts = list(msg.walk()) if msg.is_multipart() else [msg]
        for part in parts:
            kind = part.get_content_type()
            if kind not in ("text/plain", "text/html"):
                continue
            payload = part.get_payload(decode=True)
            if not payload:
                continue
            try:
                text = payload.decode(part.get_content_charset() or "utf-8", errors="ignore")
            except LookupError:
                text = payload.decode("utf-8", errors="ignore")
            if kind == "text/html":
                html_parts.append(self._html_to_text(text))
            else:
                plain_parts.append(text)
        plain = "\n".join(plain_parts).strip()
        html = "\n".join(html_parts).strip()
        # Utility bills often put the amount and due date only in the HTML part.
        if len(html) > len(plain):
            return html
        return plain

    @staticmethod
    def _html_to_text(html: str) -> str:
        text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", html)
        text = re.sub(r"(?s)<[^>]+>", " ", text)
        return re.sub(r"\s+", " ", text).strip()

    def _categorize(self, subject: str, sender: str, body: str) -> str:
        header = f"{subject} {sender}".lower()
        promo = ("% off", "discount", "coupon", "promo", "flash sale", "save up to", "ships free")
        bills = ("invoice", "past due", "amount due", "payment due", "overdue", "receipt", "statement")
        if any(marker in header for marker in promo):
            return "General"
        if any(keyword in header for keyword in bills):
            return "Urgent/Bill"
        text = f"{header} {body}".lower()
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
        yahoo_email_2 = os.getenv("YAHOO_EMAIL_2")
        yahoo_password_2 = os.getenv("YAHOO_PASSWORD_2")
        if yahoo_email_2 and yahoo_password_2:
            accounts.append(
                MailAccount(
                    name="yahoo2",
                    host=os.getenv("YAHOO_IMAP_HOST", "imap.mail.yahoo.com"),
                    username=yahoo_email_2,
                    password=yahoo_password_2,
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

    def _detect_financial_urgency(
        self,
        subject: str,
        sender: str,
        body: str,
        message_id: str,
        account_name: str,
        sent_at: str = "",
        account_email: str = "",
        forced_kind: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Detect financial urgency in email and escalate to priority_inbox.
        Returns priority action info if escalation was created, None otherwise.
        """
        try:
            # Learned / seeded false positives (Not a bill on the desk).
            try:
                from bill_feedback import is_bill_suppressed

                if is_bill_suppressed(resolve_db_path("khursheed.db"), sender, subject):
                    logger.info(
                        "Skipping suppressed non-bill mail from %s subject=%r",
                        sender,
                        subject[:80],
                    )
                    return None
            except Exception as exc:  # pylint: disable=broad-except
                logger.warning("Bill suppression check failed: %s", exc)

            # Stage 1: a watched biller is always read. Everyone else needs a keyword.
            candidate_kind = self._candidate_kind(subject, sender, body) or forced_kind
            if not candidate_kind:
                return None

            # Stage 2: OpenAI extraction (expensive, only for candidates)
            extraction = self._extract_financial_details(
                subject,
                sender,
                body,
                candidate_kind,
                self._biller_note(sender),
            )
            
            if extraction.get("kind") in (None, "none"):
                return None
            # A keyword-only guess with no amount and no due date is not a bill.
            # A real due date is kept even when confidence is low, so it can be
            # raised later without reading this message again.
            if extraction.get("confidence") == "low" and not extraction.get("due_date") and extraction.get("amount") in (None, ""):
                return None

            # Priority and expiry calculation
            priority, expires_at = self._calculate_priority_and_expiry(extraction)
            
            # Create priority action
            action_id = self._create_priority_action(
                extraction,
                subject,
                sender,
                message_id,
                account_name,
                priority,
                expires_at,
                sent_at,
                account_email,
            )
            
            return {
                "action_id": action_id,
                "kind": extraction.get("kind"),
                "priority": priority
            }
            
        except Exception as e:
            logger.warning(f"Error in financial urgency detection for message {message_id}: {e}")
            return None

    def _candidate_kind(self, subject: str, sender: str, body: str) -> Optional[str]:
        """Watched billers skip the keyword gate. Other mail still has to match a phrase."""
        try:
            from billers import watched_candidate_kind

            watched = watched_candidate_kind(resolve_db_path("khursheed.db"), sender)
            if watched:
                return watched
        except Exception as exc:
            logger.warning("Biller list check failed: %s", exc)
        return self._financial_keyword_prefilter(subject, sender, body)

    def _biller_note(self, sender: str) -> str:
        try:
            from billers import find_biller

            row = find_biller(resolve_db_path("khursheed.db"), sender)
        except Exception:
            return ""
        if not row:
            return ""
        label = row["kind"].replace("_", " ")
        return f"{row['display_name']} ({row['domain']}, {label})"

    def _financial_keyword_prefilter(self, subject: str, sender: str, body: str) -> Optional[str]:
        """Stage 1: Cheap keyword-based prefiltering"""
        text = f"{subject} {sender} {body}".lower()
        sender_l = (sender or "").lower()

        # new_bill keywords — avoid bare "bill"/"tax" which fire on newsletters.
        new_bill_keywords = [
            "invoice",
            "statement available",
            "statement is available",
            "account statement",
            "upcoming bill",
            "bill estimate",
            "amount due",
            "payment due",
            "your invoice",
            "new statement",
            "billing statement",
            "your bill",
            "bill is due",
            "pay your bill",
            "pay this bill",
            "bill amount",
            "ebill",
            "e-bill",
            "please pay",
        ]

        # overdue_payment keywords
        overdue_keywords = [
            "past due", "overdue", "payment failed",
            "account suspended", "service disconnection", "payment overdue",
        ]
        # These phrases also appear in sales mail ("final notice: 30% off").
        overdue_with_payment = ["final notice", "second notice"]
        promo_markers = ["% off", "discount", "coupon", "promo", "ends at midnight"]
        payment_markers = [
            "invoice",
            "past due",
            "amount due",
            "payment due",
            "payment failed",
            "your bill",
            "bill is due",
            "pay your bill",
        ]
        strong_payment_markers = [
            "invoice",
            "amount due",
            "payment due",
            "payment failed",
            "receipt for your payment",
            "your bill is ready",
        ]

        # trial_ending keywords
        trial_keywords = [
            "trial ends", "trial expires", "free trial expires", "cancel before", "will be charged on",
            "will be deactivated", "deactivated soon",
            "auto-renew on", "subscription renewal", "trial expiring", "trial period ends"
        ]

        # Newsletters / digests are almost never personal invoices unless strong
        # payment language is present.
        newsletter_sender = bool(
            re.search(r"\b(newsletter|digest|news|updates)@", sender_l)
            or "newsletter@" in sender_l
            or "aisecret" in sender_l
        )
        if newsletter_sender and not any(marker in text for marker in strong_payment_markers):
            return None

        # A discount email is not a bill, even when the subject says "final notice".
        if any(marker in text for marker in promo_markers) and not any(
            marker in text for marker in payment_markers
        ):
            return None

        notice_is_a_bill = any(keyword in text for keyword in overdue_with_payment) and any(
            marker in text for marker in payment_markers
        )
        # Check most specific patterns first
        if any(keyword in text for keyword in trial_keywords):
            return "trial_ending"
        elif any(keyword in text for keyword in overdue_keywords) or notice_is_a_bill:
            return "overdue_payment"
        elif any(keyword in text for keyword in new_bill_keywords):
            return "new_bill"

        return None

    @staticmethod
    def _parse_model_json(result_text: str) -> Dict[str, Any]:
        text = (result_text or "").strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?", "", text, flags=re.IGNORECASE).strip()
            text = re.sub(r"```$", "", text).strip()
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            text = text[start:end + 1]
        return json.loads(text)

    def _extract_financial_details(
        self,
        subject: str,
        sender: str,
        body: str,
        candidate_kind: str,
        biller_note: str = "",
    ) -> Dict[str, Any]:
        """Stage 2: OpenAI extraction or fallback to keyword-only"""
        try:
            # Check if OpenAI is available
            openai_key = os.getenv("OPENAI_API_KEY")
            if not openai_key:
                return self._fallback_extraction(subject, sender, body, candidate_kind)

            # Try OpenAI extraction
            import openai
            client = openai.OpenAI(api_key=openai_key)
            
            prompt = f"""
Analyze this email and decide if the recipient must pay or will be auto-charged.

Subject: {subject}
From: {sender}
Body: {body[:2000]}

Return ONLY valid JSON with:
- kind: one of "new_bill", "overdue_payment", "trial_ending", or "none"
- vendor: company/service the recipient owes, or null
- amount: numeric amount owed by the recipient, or null
- currency: currency code (USD, EUR, etc) or null
- due_date: YYYY-MM-DD if the recipient has a due date, else null
- confidence: "high", "medium", or "low"
- action_required: brief description, or null when kind is "none"

Rules:
- Use kind "none" for newsletters, news digests, opinion/policy articles, marketing,
  education, or general discussion of taxes/bills/invoices/prices that do NOT ask
  this recipient to pay a specific personal charge.
- Example that must be "none": a newsletter titled about Europe taxes from a
  publisher (e.g. AI Secret) that mentions EUR amounts in the article.
- Only use new_bill / overdue_payment / trial_ending when the recipient is asked
  to pay for a product/service they use, or a trial/subscription will charge them.
- Never invent vendor, amount, currency, or due_date. If unsure, kind="none".
- Newsletter senders (newsletter@, news@, digests) are "none" unless the body
  clearly contains a personal invoice or payment request for this recipient.
            """
            if biller_note:
                prompt += f"""

This sender is on the user's biller list: {biller_note}.
Still return kind "none" for security alerts, marketing, shipping notices, and
payments the recipient sent to someone else.
Do keep a personal invoice, a card or utility statement, a subscription receipt,
or a renewal that charges this recipient.
"""

            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=200,
                temperature=0.1
            )
            
            result_text = response.choices[0].message.content or ""
            extraction = self._parse_model_json(result_text)
            
            # Validate required fields
            if not isinstance(extraction.get("kind"), str):
                raise ValueError("Invalid extraction format")
                
            return extraction
            
        except Exception as e:
            logger.warning(f"OpenAI extraction failed, falling back to keyword-only: {e}")
            return self._fallback_extraction(subject, sender, body, candidate_kind)

    def _fallback_extraction(self, subject: str, sender: str, body: str, candidate_kind: str) -> Dict[str, Any]:
        """Fallback keyword-only extraction when OpenAI unavailable/fails"""
        text = f"{subject} {sender} {body}".lower()
        
        # Extract vendor name from sender
        vendor = "Unknown"
        if "@" in sender:
            domain_match = re.search(r"@([^.]+)", sender)
            if domain_match:
                vendor = domain_match.group(1).capitalize()
        
        # Try to extract amount
        amount_match = re.search(r"(?<![\d.])[$€£¥]?(\d+(?:\.\d+)?)(?![\d.])(?!\s*%)", text)
        amount = float(amount_match.group(1)) if amount_match else None
        
        # Try to extract currency
        currency = None
        if "$" in text: currency = "USD"
        elif "€" in text: currency = "EUR"
        elif "£" in text: currency = "GBP"
        elif "¥" in text: currency = "JPY"
        
        # Try to extract due date (basic patterns)
        due_date = None
        from priority_inbox import normalize_due_date

        date_patterns = [
            r"due[:\s]+(\d{1,2}/\d{1,2}/\d{4})",
            r"by[:\s]+(\d{1,2}/\d{1,2}/\d{4})",
            r"expires?[:\s]+(\d{1,2}/\d{1,2}/\d{4})",
            r"(\d{4}-\d{2}-\d{2})",
            r"\b(\d{1,2}/\d{1,2}/\d{4})\b",
        ]
        for pattern in date_patterns:
            match = re.search(pattern, text)
            if match:
                due_date = normalize_due_date(match.group(1))
                if due_date:
                    break

        return {
            "kind": candidate_kind,
            "vendor": vendor,
            "amount": amount,
            "currency": currency,
            "due_date": due_date,
            "confidence": "low",
            "action_required": f"Review {candidate_kind} from {vendor}"
        }

    def _calculate_priority_and_expiry(self, extraction: Dict[str, Any]) -> tuple[int, Optional[str]]:
        """Calculate priority and expiry based on extraction data."""
        from priority_inbox import normalize_due_date
        from priority_inbox import priority_for_bill

        normalized = normalize_due_date(extraction.get("due_date"))
        if normalized:
            extraction["due_date"] = normalized
        return priority_for_bill(extraction.get("kind") or "", normalized)

    def _create_priority_action(
        self, extraction: Dict[str, Any], subject: str, sender: str,
        message_id: str, account_name: str, priority: int, expires_at: Optional[str],
        sent_at: str = "",
        account_email: str = "",
    ) -> str:
        """Create priority action using priority_inbox"""
        try:
            from priority_inbox import emit_priority_action
            
            kind = extraction.get("kind", "financial")
            vendor = extraction.get("vendor", "Unknown")
            amount = extraction.get("amount", "")
            currency = extraction.get("currency", "")
            due_date = extraction.get("due_date", "Unknown")
            
            # Format title
            amount_str = f"{amount} {currency}".strip() if amount else "amount unknown"
            title = f"{kind}: {vendor} - {amount_str} due {due_date}"
            
            # Create source key for deduplication
            source_key = hashlib.sha256(
                f"{account_name}|{message_id}|{kind}".encode()
            ).hexdigest()
            
            action_id = emit_priority_action(
                kind=kind,
                title=title,
                description=subject,
                payload={
                    **extraction,
                    "message_id": message_id,
                    "account": account_name,
                    "subject": subject,
                    "from": sender,
                    "sent_at": sent_at,
                    "account_email": account_email,
                },
                priority=priority,
                source_key=source_key,
                expires_at=expires_at
            )
            
            logger.info(f"Created priority action {action_id} for {kind} from {vendor} (priority {priority})")
            return action_id
            
        except Exception as e:
            logger.error(f"Failed to create priority action for {kind}: {e}")
            raise
