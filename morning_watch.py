"""Morning check for the Railway process.

The Mac keeps using cron. A Railway volume attaches to one service, so the
web process is the only writer of khursheed.db and the only morning runner.
"""

from __future__ import annotations

import importlib.util
import logging
import os
import threading
import time
from pathlib import Path


logger = logging.getLogger(__name__)
_started = False


def start_if_railway() -> None:
    """Start one background check. Local runs leave this idle."""
    global _started
    if _started or not os.getenv("RAILWAY_ENVIRONMENT", "").strip():
        return
    _started = True
    threading.Thread(target=_loop, name="morning-watch", daemon=True).start()


def _loop() -> None:
    run = _load_morning_main()
    while True:
        try:
            run()
        except Exception:
            logger.exception("Morning watch failed")
        time.sleep(60)


def _load_morning_main():
    path = Path(__file__).resolve().parent / "scripts" / "morning_run.py"
    spec = importlib.util.spec_from_file_location("khursheed_morning_run", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.main
