#!/usr/bin/env python3
"""Generate the weekly executive summary and email it to SUMMARY_TO."""
import os
import sys

from dotenv import load_dotenv

from executive_summary import generate_executive_summary
from manager import Manager
from notifications import CompositeNotifier, EmailNotifier, MarkdownFileNotifier
from skills import EchoSkill, LeadScoutSkill, SifterSkill, TimestampSkill


def main() -> None:
    load_dotenv(override=True)

    sender = os.getenv("GMAIL_EMAIL")
    password = os.getenv("GMAIL_PASSWORD")
    recipient = os.getenv("SUMMARY_TO")

    if not sender or not password:
        print("ERROR: GMAIL_EMAIL and GMAIL_PASSWORD must be set in .env", file=sys.stderr)
        sys.exit(1)
    if not recipient:
        print("ERROR: SUMMARY_TO must be set in .env", file=sys.stderr)
        sys.exit(1)

    manager = Manager()
    manager.register_many([EchoSkill(), LeadScoutSkill(), SifterSkill(), TimestampSkill()])

    notifier = CompositeNotifier(
        MarkdownFileNotifier(),
        EmailNotifier(sender=sender, password=password, recipient=recipient),
    )

    print(f"Generating executive summary and emailing to {recipient}...")
    report = generate_executive_summary(manager, notifier)
    print("Done.")
    print(report)


if __name__ == "__main__":
    main()
