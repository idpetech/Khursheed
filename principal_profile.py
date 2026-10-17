"""Load the principal profile that Hey Eman prepends to every prompt."""

from __future__ import annotations

import json
from pathlib import Path

from runtime import PROJECT_ROOT


DEFAULT_PROFILE_PATH = PROJECT_ROOT / "config" / "principal.json"


def principal_prompt_block(path: str | Path | None = None) -> str:
    """Return a prompt block for filled profile fields. Empty and missing files add nothing."""
    profile_path = Path(path) if path else DEFAULT_PROFILE_PATH
    data = _read_profile(profile_path)
    if not data:
        return ""
    lines = []
    goals = _strings(data.get("goals"))
    if goals:
        lines.append("Goals: " + "; ".join(goals))
    icp = _text(data.get("icp"))
    if icp:
        lines.append("ICP: " + icp)
    voice = _text(data.get("voice"))
    if voice:
        lines.append("Voice: " + voice)
    will_not = _strings(data.get("will_not"))
    if will_not:
        lines.append("Will not: " + "; ".join(will_not))
    people = _strings(data.get("people"))
    if people:
        lines.append("People: " + "; ".join(people))
    if not lines:
        return ""
    body = "\n".join(f"- {line}" for line in lines)
    return f"\n\nPrincipal profile:\n{body}"


def _read_profile(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    return data


def _text(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip()


def _strings(value: object) -> list[str]:
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if isinstance(value, list):
        items = []
        for item in value:
            text = str(item).strip()
            if text:
                items.append(text)
        return items
    return []
