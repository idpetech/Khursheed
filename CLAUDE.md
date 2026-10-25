# Khursheed / Enaam — read this before changing architecture

This file wins over `PORT_ALLOCATION.md`, `ENAAM_COMMAND_CENTER.md`, `VALIDATION_REPORT.md`, and `scripts/start_enaam_services.sh` when those disagree about what is running.

## The live desk

The daily app is `hey_eman_app.py`, Streamlit, from `.venv`, on port **8510**.

It reads mail, stores bills, sends WhatsApp, and answers chat. It does not import the `enaam/` package. Confirm the live process with the listener on 8510 before calling any other file production.

Do not start `scripts/start_enaam_services.sh`. It launches a different stack and treats port 8510 as a conflict it may kill.

## The other stack

`enaam_ui.py` (8501), `enaam_admin.py` (8502), `enaam_skill_api.py` (5001), and `enaam/mcp_server.py` (8080) are an older stack still in the tree. Root modules `enaam_adapter.py`, `enaam_orchestrator.py`, and `enaam_skill_loader.py` belong to that stack. `enaam/integrations/khursheed_bridge.py` reaches them with a `sys.path` append.

Do not delete those files, and do not finish a dependency-injection rewrite of them, unless the task is specifically about that stack. Commit `fd6c48c` only renamed Victor files to Enaam. It did not create the split.

## Checks that were wrong once

- `ruff check .` already skips `venv/` and `.venv/`. A large lint count is project code.
- A `global`-statement count that includes `invalid-syntax` is not a count of globals.
- `requirements.txt` is the desk install list. Do not drop `openai` because `pyproject.toml` used to omit it.
- `VALIDATION_REPORT.md` (2026-05-24) is not proof of the current architecture. Global-state elimination does not pass.
- `venv/` must stay untracked. The desk uses `.venv`.
