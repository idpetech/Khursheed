"""Side effect and model-call maximum for each live skill.

Keyed by skill name. Echo, timestamp, calculator, weather, file_analyzer, and
scout stay registered and are not declared here.

A caller states the model calls it wants in payload["model_calls"]. When that
count is above the maximum, run_skill refuses and does not call the skill.
Omitting the count leaves the skill's own calls alone.
"""

from __future__ import annotations

from typing import Any


READ_ONLY = "read-only"
REVERSIBLE = "reversible"
EXTERNAL = "external"

# One row per live skill. The number is the most model calls one run may make.
DECLARATIONS: dict[str, dict[str, Any]] = {
    "icp_finder": {"side_effect": REVERSIBLE, "max_model_calls": 1},
    "cto_radar": {"side_effect": REVERSIBLE, "max_model_calls": 0},
    "lead_scout": {"side_effect": READ_ONLY, "max_model_calls": 0},
    "icp_prospector": {"side_effect": READ_ONLY, "max_model_calls": 2},
    "outreach_draft": {"side_effect": REVERSIBLE, "max_model_calls": 0},
    "sifter": {"side_effect": REVERSIBLE, "max_model_calls": 100},
    "calendar_prep": {"side_effect": READ_ONLY, "max_model_calls": 0},
    "blogger": {"side_effect": EXTERNAL, "max_model_calls": 1},
    "ceo_advisor": {"side_effect": REVERSIBLE, "max_model_calls": 2},
}


def declaration_refusal(
    skill_name: str,
    payload: dict[str, Any] | None,
    *,
    called_by_skill: bool,
    caller: str | None,
) -> dict[str, Any] | None:
    """Return a refusal when this run breaks a declaration. None means proceed."""
    if caller == "ceo_advisor":
        return {
            "status": "refused",
            "message": "The CEO skill does not run another skill.",
        }
    row = DECLARATIONS.get(skill_name)
    if row is None:
        return None
    if called_by_skill and row["side_effect"] == EXTERNAL:
        return {
            "status": "refused",
            "published": False,
            "message": f"A skill cannot run {skill_name}. It is external.",
        }
    requested = _requested_model_calls(payload)
    maximum = row["max_model_calls"]
    if requested is not None and requested > maximum:
        return {
            "status": "refused",
            "message": (
                f"{skill_name} allows {maximum} model calls. "
                f"This run asked for {requested}, so it was not called."
            ),
        }
    return None


def _requested_model_calls(payload: dict[str, Any] | None) -> int | None:
    if not isinstance(payload, dict) or "model_calls" not in payload:
        return None
    raw = payload["model_calls"]
    if isinstance(raw, bool) or not isinstance(raw, int) or raw < 0:
        return 10**9
    return raw
