"""Single skill list used by the CLI, Hey Eman, ask.py, and the orchestrator."""

from __future__ import annotations

import sqlite3
from datetime import UTC
from datetime import datetime
from typing import TYPE_CHECKING

from skills.base import Skill
from skills.blogger import BloggerSkill
from skills.calculator import CalculatorSkill
from skills.cto_radar import CtoRadarSkill
from skills.echo import EchoSkill
from skills.file_analyzer import FileAnalyzerSkill
from skills.icp_prospector import IcpProspectorSkill
from skills.lead_scout import LeadScoutSkill
from skills.scout import ScoutSkill
from skills.sifter import SifterSkill
from skills.timestamp import TimestampSkill
from skills.weather import WeatherSkill


if TYPE_CHECKING:
    from manager import Manager


DEFAULT_SKILL_CLASSES: list[type[Skill]] = [
    EchoSkill,
    TimestampSkill,
    CalculatorSkill,
    WeatherSkill,
    FileAnalyzerSkill,
    LeadScoutSkill,
    ScoutSkill,
    SifterSkill,
    CtoRadarSkill,
    IcpProspectorSkill,
    BloggerSkill,
]


def default_skill_names() -> list[str]:
    return [skill_class.name for skill_class in DEFAULT_SKILL_CLASSES]


def register_default_skills(manager: Manager) -> list[Skill]:
    """Register every default skill and mirror them into the database registry."""
    instances = [skill_class() for skill_class in DEFAULT_SKILL_CLASSES]
    manager.register_many(instances)
    _upsert_skill_records(manager, instances)
    return instances


def _description(skill: Skill) -> str | None:
    doc = (skill.__class__.__doc__ or "").strip()
    if not doc:
        return None
    return doc.splitlines()[0].strip()


def _upsert_skill_records(manager: Manager, skills: list[Skill]) -> None:
    now = datetime.now(UTC).isoformat()
    connection = manager._connection
    with connection:
        for skill in skills:
            description = _description(skill)
            module_path = skill.__class__.__module__
            class_name = skill.__class__.__name__
            connection.execute(
                """
                INSERT INTO skill_registry (
                    skill_name, skill_class, module_path, description, enabled, last_registered_at
                ) VALUES (?, ?, ?, ?, 1, ?)
                ON CONFLICT(skill_name) DO UPDATE SET
                    skill_class = excluded.skill_class,
                    module_path = excluded.module_path,
                    description = excluded.description,
                    enabled = 1,
                    last_registered_at = excluded.last_registered_at
                """,
                (skill.name, class_name, module_path, description, now),
            )
            try:
                connection.execute(
                    """
                    INSERT INTO skill_configurations (
                        skill_name, skill_class, skill_module, enabled, config_json, description
                    ) VALUES (?, ?, ?, 1, '{}', ?)
                    ON CONFLICT(skill_name) DO UPDATE SET
                        skill_class = excluded.skill_class,
                        skill_module = excluded.skill_module,
                        enabled = 1,
                        description = excluded.description
                    """,
                    (skill.name, class_name, module_path, description),
                )
            except sqlite3.OperationalError:
                # Fresh databases always have this table after migrations.
                # A caller that registers skills before migrations should not lose the in-memory set.
                continue
