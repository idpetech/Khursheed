from dotenv import load_dotenv

from executive_summary import generate_executive_summary
from manager import Manager
from notifications import MarkdownFileNotifier
from skills import EchoSkill, LeadScoutSkill, SifterSkill, TimestampSkill


def main() -> None:
    load_dotenv(override=True)
    manager = Manager()
    manager.register_many([EchoSkill(), LeadScoutSkill(), SifterSkill(), TimestampSkill()])
    tasks = manager.load_tasks("tasks.json")
    manager.run_tasks(tasks)
    generate_executive_summary(manager, MarkdownFileNotifier())


if __name__ == "__main__":
    main()
