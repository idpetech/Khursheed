from datetime import datetime, timezone
from typing import Any, Dict

from skills.base import Skill


class TimestampSkill(Skill):
    name = "timestamp"

    def run(self, task: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "task_id": task.get("id"),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
