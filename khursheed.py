from dotenv import load_dotenv

from executive_summary import generate_executive_summary
from manager import Manager
from notifications import MarkdownFileNotifier
from runtime import prepare_runtime
from skills_bootstrap import register_default_skills


def main() -> None:
    load_dotenv(override=True)
    prepare_runtime()
    manager = Manager()
    register_default_skills(manager)
    tasks = manager.load_tasks("tasks.json")
    manager.run_tasks(tasks)
    generate_executive_summary(manager, MarkdownFileNotifier())


if __name__ == "__main__":
    main()
