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
        priority_actions: List[Dict[str, Any]] = []

        for account in self._accounts:
            categorized, account_priority_actions = self._process_account(account, max_messages)
            results.append({"account": account.name, "categorized": categorized})
            priority_actions.extend(account_priority_actions)
            for entry in categorized:
                if entry.get("expense"):
                    expenses.append(entry["expense"])

        self._save_expenses(expenses)
        return {"accounts": results, "expense_count": len(expenses), "priority_actions": priority_actions}

    def _process_account(self, account: MailAccount, max_messages: int) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        categorized: List[Dict[str, Any]] = []
        priority_actions: List[Dict[str, Any]] = []
        since_date = (datetime.now(timezone.utc) - timedelta(days=2)).strftime("%d-%b-%Y")
        
        try:
            with imaplib.IMAP4_SSL(account.host) as imap:
                imap.login(account.username, account.password)
                imap.select("INBOX")
                status, data = imap.search(None, "SINCE", since_date)
                if status != "OK":
                    return categorized, priority_actions
                message_ids = data[0].split()
                for msg_id in message_ids[-max_messages:]:
                    try:
                        msg = self._fetch_message(imap, msg_id)
                        if msg is None:
                            continue
                        subject = self._decode_header(msg.get("Subject", ""))
                        sender = self._decode_header(msg.get("From", ""))
                        body = self._extract_body(msg)
                        category = self._categorize(subject, sender, body)
                        expense = self._extract_expense(subject, sender, body)
                        
                        # Add financial detection (new layer on top)
                        message_id = msg.get("Message-ID", f"unknown-{msg_id.decode()}")
                        financial_detection = self._detect_financial_urgency(
                            subject, sender, body, message_id, account.name
                        )
                        if financial_detection:
                            priority_actions.append(financial_detection)
                        
                        categorized.append(
                            {
                                "subject": subject,
                                "from": sender,
                                "category": category,
                                "expense": expense,
                            }
                        )
                    except Exception as e:
                        logger.warning(f"Error processing message {msg_id} in account {account.name}: {e}")
                        continue
        except Exception as e:
            logger.error(f"Error connecting to account {account.name}: {e}")
            
        return categorized, priority_actions

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

    def _detect_financial_urgency(self, subject: str, sender: str, body: str, message_id: str, account_name: str) -> Optional[Dict[str, Any]]:
        """
        Detect financial urgency in email and escalate to priority_inbox.
        Returns priority action info if escalation was created, None otherwise.
        """
        try:
            # Stage 1: Keyword prefilter (cheap)
            financial_kind = self._financial_keyword_prefilter(subject, sender, body)
            if not financial_kind:
                return None

            # Stage 2: OpenAI extraction (expensive, only for candidates)
            extraction = self._extract_financial_details(subject, sender, body, financial_kind)
            
            if extraction.get("kind") == "none":
                return None

            # Priority and expiry calculation
            priority, expires_at = self._calculate_priority_and_expiry(extraction)
            
            # Create priority action
            action_id = self._create_priority_action(
                extraction, subject, sender, message_id, account_name, priority, expires_at
            )
            
            return {
                "action_id": action_id,
                "kind": extraction.get("kind"),
                "priority": priority
            }
            
        except Exception as e:
            logger.warning(f"Error in financial urgency detection for message {message_id}: {e}")
            return None

    def _financial_keyword_prefilter(self, subject: str, sender: str, body: str) -> Optional[str]:
        """Stage 1: Cheap keyword-based prefiltering"""
        text = f"{subject} {sender} {body}".lower()
        
        # new_bill keywords
        new_bill_keywords = [
            "invoice", "statement available", "amount due", "payment due", "bill", 
            "your invoice", "new statement", "billing statement"
        ]
        
        # overdue_payment keywords  
        overdue_keywords = [
            "past due", "overdue", "payment failed", "final notice", "second notice",
            "account suspended", "service disconnection", "payment overdue"
        ]
        
        # trial_ending keywords
        trial_keywords = [
            "trial ends", "trial expires", "free trial expires", "cancel before", "will be charged on",
            "auto-renew on", "subscription renewal", "trial expiring", "trial period ends"
        ]
        
        # Check most specific patterns first 
        if any(keyword in text for keyword in trial_keywords):
            return "trial_ending"
        elif any(keyword in text for keyword in overdue_keywords):
            return "overdue_payment"
        elif any(keyword in text for keyword in new_bill_keywords):
            return "new_bill"
            
        return None

    def _extract_financial_details(self, subject: str, sender: str, body: str, candidate_kind: str) -> Dict[str, Any]:
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
            Analyze this email for financial urgency and extract details in strict JSON format.
            
            Subject: {subject}
            From: {sender}
            Body: {body[:2000]}  # Truncate for API limits
            
            Extract these fields in JSON:
            - kind: one of "new_bill", "overdue_payment", "trial_ending", or "none"
            - vendor: company/service name
            - amount: numeric amount if found
            - currency: currency code (USD, EUR, etc) or null
            - due_date: YYYY-MM-DD format if found, or null
            - confidence: "high", "medium", or "low"
            - action_required: brief description of what action is needed
            
            Return ONLY valid JSON, no other text.
            """

            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=200,
                temperature=0.1
            )
            
            result_text = response.choices[0].message.content.strip()
            extraction = json.loads(result_text)
            
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
        amount_match = re.search(r"[\$€£¥]?(\d+\.?\d*)", text)
        amount = float(amount_match.group(1)) if amount_match else None
        
        # Try to extract currency
        currency = None
        if "$" in text: currency = "USD"
        elif "€" in text: currency = "EUR"
        elif "£" in text: currency = "GBP"
        elif "¥" in text: currency = "JPY"
        
        # Try to extract due date (basic patterns)
        due_date = None
        date_patterns = [
            r"due (\d{1,2}/\d{1,2}/\d{4})",
            r"(\d{4}-\d{2}-\d{2})",
            r"expires? (\d{1,2}/\d{1,2}/\d{4})"
        ]
        for pattern in date_patterns:
            match = re.search(pattern, text)
            if match:
                try:
                    # Convert to YYYY-MM-DD format
                    date_str = match.group(1)
                    if "/" in date_str:
                        parts = date_str.split("/")
                        if len(parts) == 3:
                            due_date = f"{parts[2]}-{parts[0]:0>2}-{parts[1]:0>2}"
                    else:
                        due_date = date_str
                    break
                except:
                    continue

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
        """Calculate priority and expiry based on extraction data"""
        kind = extraction.get("kind")
        due_date = extraction.get("due_date")
        
        # overdue_payment -> priority 3, no expiry
        if kind == "overdue_payment":
            return 3, None
            
        # For new_bill and trial_ending, calculate based on due/end date
        if due_date:
            try:
                due_dt = datetime.fromisoformat(due_date + "T23:59:59")
                now = datetime.now()
                days_until = (due_dt - now).days
                
                if days_until <= 2:
                    priority = 3  # Urgent
                elif days_until <= 7:
                    priority = 2  # High
                else:
                    priority = 1  # Medium
                    
                # Set expiry to the due date
                expires_at = due_dt.isoformat()
                return priority, expires_at
                
            except (ValueError, TypeError):
                # Invalid date format, default to medium priority
                pass
        
        # Default for new_bill/trial_ending without valid date
        return 1, None

    def _create_priority_action(
        self, extraction: Dict[str, Any], subject: str, sender: str, 
        message_id: str, account_name: str, priority: int, expires_at: Optional[str]
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
                    "from": sender
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
