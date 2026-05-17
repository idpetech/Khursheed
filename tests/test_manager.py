import os
import tempfile
import unittest

from manager import Manager
from skills.base import Skill


class DummySkill(Skill):
    name = "dummy"

    def run(self, task):
        return {"task_id": task.get("id"), "status": "ok"}


class ManagerTests(unittest.TestCase):
    def test_manager_records_runs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            manager = Manager(db_path=db_path)
            manager.register(DummySkill())
            tasks = [{"id": "task-1", "skills": ["dummy"]}]
            manager.run_tasks(tasks)
            manager.run_tasks(tasks)

            cursor = manager._connection.execute(
                "SELECT COUNT(*) FROM skill_runs WHERE task_id = ? AND skill_name = ?",
                ("task-1", "dummy"),
            )
            count = cursor.fetchone()[0]
            self.assertEqual(count, 1)


if __name__ == "__main__":
    unittest.main()
