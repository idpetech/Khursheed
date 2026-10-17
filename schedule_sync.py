"""Sync tasks.json into scheduled_jobs and run the jobs that are due."""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Iterable
from datetime import UTC
from datetime import datetime
from datetime import timedelta
from typing import TYPE_CHECKING
from typing import Any


if TYPE_CHECKING:
    from manager import Manager


logger = logging.getLogger(__name__)

ONE_SHOT_HORIZON = timedelta(days=36500)


def sync_and_run(manager: Manager, tasks: Iterable[dict[str, Any]]) -> None:
    """Upsert the given tasks, then run whichever of those jobs are due."""
    now = datetime.now(UTC)
    job_names: list[str] = []
    task_list = list(tasks)
    with manager._connection:
        for task in task_list:
            task_id = task["id"]
            payload = task.get("payload") or {}
            interval_days = task.get("interval_days")
            for skill_name in task.get("skills", []):
                job_name = f"{task_id}:{skill_name}"
                job_names.append(job_name)
                next_run = _next_run_at(manager, task_id, skill_name, interval_days, now)
                _upsert_job(
                    manager,
                    job_name,
                    skill_name,
                    task_id,
                    payload,
                    interval_days,
                    next_run,
                    now,
                )
    _run_due_jobs(manager, job_names, now)


def _next_run_at(
    manager: Manager,
    task_id: str,
    skill_name: str,
    interval_days: int | None,
    now: datetime,
) -> datetime:
    last_run = manager._last_run_at(task_id, skill_name)
    if last_run is None:
        return now
    if interval_days is None:
        return last_run + ONE_SHOT_HORIZON
    return last_run + timedelta(days=int(interval_days))


def _upsert_job(
    manager: Manager,
    job_name: str,
    skill_name: str,
    task_id: str,
    payload: dict[str, Any],
    interval_days: int | None,
    next_run: datetime,
    now: datetime,
) -> None:
    schedule_type = "interval" if interval_days is not None else "one_time"
    schedule_config = {
        "type": schedule_type,
        "interval_days": interval_days,
        "task_id": task_id,
    }
    now_text = now.isoformat()
    manager._connection.execute(
        """
        INSERT INTO scheduled_jobs (
            job_id, job_name, job_type, target, payload_json, schedule_type,
            schedule_config, next_run_at, enabled, created_at, updated_at
        ) VALUES (?, ?, 'skill', ?, ?, ?, ?, ?, 1, ?, ?)
        ON CONFLICT(job_name) DO UPDATE SET
            target = excluded.target,
            payload_json = excluded.payload_json,
            schedule_type = excluded.schedule_type,
            schedule_config = excluded.schedule_config,
            next_run_at = excluded.next_run_at,
            enabled = 1,
            updated_at = excluded.updated_at
        """,
        (
            str(uuid.uuid4()),
            job_name,
            skill_name,
            json.dumps(payload),
            schedule_type,
            json.dumps(schedule_config),
            next_run.isoformat(),
            now_text,
            now_text,
        ),
    )


def _run_due_jobs(manager: Manager, job_names: list[str], now: datetime) -> None:
    if not job_names:
        return
    wanted = set(job_names)
    cursor = manager._connection.execute(
        """
        SELECT job_name, target, payload_json, schedule_config
        FROM scheduled_jobs
        WHERE enabled = 1 AND next_run_at <= ?
        ORDER BY next_run_at ASC
        """,
        (now.isoformat(),),
    )
    due_jobs = [row for row in cursor.fetchall() if row[0] in wanted]
    for job_name, target, payload_json, schedule_config_json in due_jobs:
        schedule_config = json.loads(schedule_config_json)
        task_id = schedule_config.get("task_id") or job_name.split(":", 1)[0]
        payload = json.loads(payload_json or "{}")
        status = "success"
        error = None
        try:
            manager.run_skill(target, task_id, payload)
        except KeyError:
            raise
        except Exception as exc:
            status = "failed"
            error = str(exc)
            logger.exception("Scheduled skill %s failed for %s", target, task_id)
            manager._record_run(
                task_id,
                target,
                {"error": error},
                status="failed",
                error_message=error,
            )
        _mark_ran(manager, job_name, status, error, schedule_config, datetime.now(UTC))


def _mark_ran(
    manager: Manager,
    job_name: str,
    status: str,
    error: str | None,
    schedule_config: dict[str, Any],
    now: datetime,
) -> None:
    interval_days = schedule_config.get("interval_days")
    next_run = now + ONE_SHOT_HORIZON if interval_days is None else now + timedelta(days=int(interval_days))
    now_text = now.isoformat()
    with manager._connection:
        manager._connection.execute(
            """
            UPDATE scheduled_jobs
            SET last_run_at = ?, last_status = ?, last_error = ?,
                next_run_at = ?, run_count = run_count + 1, updated_at = ?
            WHERE job_name = ?
            """,
            (now_text, status, error, next_run.isoformat(), now_text, job_name),
        )
