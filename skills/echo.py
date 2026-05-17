from typing import Any, Dict

from skills.base import Skill


class EchoSkill(Skill):
    name = "echo"

    def run(self, task: Dict[str, Any]) -> Dict[str, Any]:
        payload = task.get("payload", {})
        message = payload.get("message", "")
        return {"message": message, "task_id": task.get("id")}
