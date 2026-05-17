from executive_summary import generate_executive_summary
from manager import Manager
from notifications import MarkdownFileNotifier
from skills import EchoSkill, LeadScoutSkill, TimestampSkill


def main() -> None:
    manager = Manager()
    manager.register_many([EchoSkill(), LeadScoutSkill(), TimestampSkill()])
    tasks = manager.load_tasks("tasks.json")
    manager.run_tasks(tasks)
    generate_executive_summary(manager, MarkdownFileNotifier())


if __name__ == "__main__":
    main()
