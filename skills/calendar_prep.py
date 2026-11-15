"""Read the next meetings from an ICS feed. Stay quiet when the feed is down."""

from __future__ import annotations

import logging
import re
import ssl
from datetime import UTC
from datetime import datetime
from typing import Any
from urllib.request import urlopen

import certifi

from skills.base import Skill


logger = logging.getLogger(__name__)


class CalendarPrepSkill(Skill):
    name = "calendar_prep"

    def run(self, task: dict[str, Any]) -> dict[str, Any]:
        payload = task.get("payload") or {}
        url = str(payload.get("ics_url") or "").strip()
        if not url:
            return {"meetings": [], "error": "No calendar address is saved in Config."}
        try:
            text = _fetch(url)
            meetings = upcoming_meetings(text)
        except Exception as exc:
            logger.warning("Calendar prep could not read the feed: %s", exc)
            return {"meetings": [], "error": str(exc)}
        return {"meetings": meetings[:3]}


def _fetch(url: str) -> str:
    context = ssl.create_default_context(cafile=certifi.where())
    with urlopen(url, timeout=20, context=context) as response:
        return response.read().decode("utf-8", errors="replace")


def upcoming_meetings(ics_text: str, now: datetime | None = None) -> list[dict[str, str]]:
    """Return future events from a simple ICS file. All-day dates count for that day."""
    moment = now or datetime.now(UTC)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    unfolded = re.sub(r"\r?\n[ \t]", "", ics_text)
    found: list[tuple[datetime, str]] = []
    for block in re.split(r"BEGIN:VEVENT", unfolded, flags=re.IGNORECASE)[1:]:
        body = block.split("END:VEVENT", 1)[0]
        summary = _field(body, "SUMMARY") or "Meeting"
        start = _parse_start(_field(body, "DTSTART"))
        if start is None:
            continue
        if start.tzinfo is None:
            start = start.replace(tzinfo=UTC)
        if start >= moment:
            found.append((start, summary))
    found.sort(key=lambda item: item[0])
    return [{"start": item[0].isoformat(), "summary": item[1]} for item in found]


def _field(body: str, name: str) -> str:
    match = re.search(rf"^{name}(?:;[^:]*)?:(.*)$", body, flags=re.IGNORECASE | re.MULTILINE)
    if not match:
        return ""
    return match.group(1).strip()


def _parse_start(value: str) -> datetime | None:
    text = value.strip()
    if not text:
        return None
    if re.fullmatch(r"\d{8}", text):
        return datetime.strptime(text, "%Y%m%d").replace(tzinfo=UTC)
    stamp = text.replace("Z", "+0000")
    for pattern in ("%Y%m%dT%H%M%S%z", "%Y%m%dT%H%M%S"):
        try:
            parsed = datetime.strptime(stamp, pattern)
        except ValueError:
            continue
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)
    return None
