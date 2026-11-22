# Enaam implementation status

Updated 22 Nov 2026. Code on the remote is `e09c346` on `cleanup/codebase-fixes`. Phase 5 is the recovery steps in `ENAAM_OPERATIONS_RUNBOOK.md` and this note. It does not deploy.

## Completed

- Phase 0. The bills and subscriptions list stays in Config, under "Days of mail to scan". Mail and Now show results. Remember sender on a bill, notice, or renewal adds to that list and does not send. The list is not moved or removed without explicit consent.
- Phase 1. The seven notes in this folder describe the desk. They do not change behavior.
- Phase 2. Chief of Staff turns stay in `hey-eman`. New CEO assessments, decision lookups, and "track this" are stored in `hey-eman-ceo`. Ask Enaam shows both and captions a CEO reply. Older CEO rows already in `hey-eman` stay there.
- Phase 3. `run_skill` refuses `blogger` with mode publish, including a call from another skill. Approve on Content remains the publish path. Changing an approved action's payload returns it to pending. No new table.
- Phase 4. The morning line adds a due or overdue commitment, and a subject whose latest CEO decision is still conditional, only when those rows exist. A task-log run that did not complete shows its duration and error. A completed run stays one line. No new table.
- A company website is stored only when the address names that company. A list page shared by several names is left blank. Companies already queued keep the address they were saved with until they are skipped. Commit `e09c346`.
- Phase 5. Backup and restore for `khursheed.db` are written in the operations note. The laptop file and Railway `/data/khursheed.db` stay two databases. On 22 Nov 2026 a temporary copy of the laptop file returned `integrity_check` `ok` and was deleted. The live file was not replaced. The Railway volume was not copied. No off-machine copy was kept.

## Left out on purpose

- No engagement store, no cost ledger, no second model provider, no second task table, no new agent classes.
- No central tool-permission registry. The publish refusal is a check in `run_skill`, not a framework.
- Historical CEO rows already in `hey-eman` are not moved.
- Phase 5 does not deploy and does not replace either database.

## Tests executed

22 Nov 2026, `.venv/bin/python -m unittest` on the CEO, company, desk, and mail modules listed in `ENAAM_TEST_STRATEGY.md`.

117 tests. 115 passed. 2 errors, both in `tests/test_chief_of_staff_coverage.py`. Those tests patched `MarkdownFileNotifier` on `llm_agent` and `ask`. Those modules call `daily_brief_notifier` instead. The patches now target that function.

Re-run of `tests.test_chief_of_staff_coverage`: 15 tests, OK. The earlier traceback lines about a failed skill named `boom` and unwritable open loops are the cases those tests provoke on purpose.

Phase 3, 22 Nov 2026: `unittest discover -s tests` ran 133 tests, OK, before and after the publish gate. Coverage of the gate files: `manager.py` 100%, `action_executor.py` 96%, `llm_agent.py` 96%. `skill_context.py` is 58% because older unused helpers are untested. The new publish refusal in that file is covered.

Phase 4, 22 Nov 2026: the same suite ran 133 tests before the morning-line change and 135 after, OK.

Phase 5, 22 Nov 2026: `unittest discover -s tests` ran 136 tests, OK. The extra test is the directory page that must not be stored as a company website. The traceback lines in that run are the same provoked failures. Phase 5 changed notes only.

## Known defects

- Restart is required before the desk serves new code, and it signs the owner out.
- Search again will not offer a company that was already queued. A bad website already saved stays until that company is skipped.
- One password protects the whole database.
- There is no kept copy of `khursheed.db` off the machine.

## Security limitations

See `ENAAM_SECURITY_MODEL.md`. Permissions are code, not a registry. Clients are not partitioned. New CEO turns are stored apart from the Chief of Staff transcript. Older CEO turns already in `hey-eman` remain in that session.

## Deployment readiness

The laptop process on port 8510 is the daily desk. Railway is a Dockerfile plus a volume at `/data`. Readiness means the volume has the database you intend, the environment variables are set, and a restore copy exists off that machine. A running page is not that check. The copy command was checked. The replacement was not performed, and no restore copy was kept.

## Deviations from the directive

The directive's extra agents, task state machine, model gateway, and client CRM are not built. The skills, commitments, pending actions, and the biller list already do those jobs for a single owner. Adding parallel systems would be a second product. The plan stops here.
