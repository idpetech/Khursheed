from dotenv import load_dotenv

from desk_settings import prepare_desk_tasks
from executive_summary import generate_executive_summary
from manager import Manager
from notifications import daily_brief_notifier
from runtime import prepare_runtime
from schedule_sync import run_morning_skills
from skills_bootstrap import register_default_skills


def main() -> None:
    load_dotenv(override=True)
    prepare_runtime()
    manager = Manager()
    register_default_skills(manager)
    tasks = prepare_desk_tasks(manager.load_tasks("tasks.json"), manager._db_path)
    run_morning_skills(manager, tasks)
    generate_executive_summary(manager, daily_brief_notifier())


if __name__ == "__main__":
    main()
