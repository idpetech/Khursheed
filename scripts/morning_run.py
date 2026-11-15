"""Start the morning run once, when Config says it is time.

Cron calls this every minute. Most minutes it exits without doing work.
The Mac's local clock is the clock that matters, and the Mac has to be awake
within 30 minutes of the configured time.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from desk_settings import get_setting
from desk_settings import morning_run_enabled
from desk_settings import morning_run_is_due
from desk_settings import set_setting
from runtime import resolve_db_path

LOCK = ROOT / "logs" / "morning_run.lock"


def _load_dotenv() -> None:
    path = ROOT / ".env"
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _lock_is_stale() -> bool:
    try:
        age = datetime.now().timestamp() - LOCK.stat().st_mtime
    except OSError:
        return False
    return age > 6 * 60 * 60


def main() -> int:
    os.chdir(ROOT)
    _load_dotenv()
    db_path = resolve_db_path("khursheed.db")
    if not morning_run_enabled(db_path):
        return 0
    now = datetime.now().astimezone()
    if not morning_run_is_due(
        now,
        get_setting(db_path, "morning_run_time", "07:00"),
        get_setting(db_path, "morning_run_last_date", ""),
    ):
        return 0

    LOCK.parent.mkdir(parents=True, exist_ok=True)
    if LOCK.exists() and _lock_is_stale():
        LOCK.unlink()
    try:
        fd = os.open(LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return 0
    try:
        os.write(fd, str(os.getpid()).encode())
        print(f"{now.isoformat()} morning run starting", flush=True)
        from khursheed import main as run_morning

        run_morning()
        set_setting(db_path, "morning_run_last_date", now.date().isoformat())
        print(f"{now.isoformat()} morning run finished", flush=True)
    finally:
        os.close(fd)
        LOCK.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
