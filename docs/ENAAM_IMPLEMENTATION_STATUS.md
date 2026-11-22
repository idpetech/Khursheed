# Enaam implementation status

Updated 22 Nov 2026. Remote is `d14a3e0` on `cleanup/codebase-fixes`. Phase 1 adds these notes and changes no behavior.

## Completed

- Live desk remains `hey_eman_app.py`, one SQLite file, existing skills.
- CEO assessments require a JSON decision. Prose is rejected and not stored.
- Approved company notes stay on Companies. Search again looks for new names.
- The bills and subscriptions list is in Config, under "Days of mail to scan". Mail and Now show results. Remember sender on a bill, notice, or renewal adds to that list and does not send. The list is not moved or removed without explicit consent.
- This folder describes the desk that exists.

## Remaining

- Chief of Staff turns stay in `hey-eman`. New CEO assessments, decision lookups, and "track this" are stored in `hey-eman-ceo`. Ask Enaam shows both and captions a CEO reply. Older CEO rows already in `hey-eman` stay there. Phase 2.
- `run_skill` refuses `blogger` with mode publish, including a call from another skill. Approve on Content remains the publish path. Changing an approved action's payload returns it to pending. Phase 3. No new table.
- The morning line adds a due or overdue commitment, and a subject whose latest CEO decision is still conditional, only when those rows exist. A task-log run that did not complete shows its duration and error. A completed run stays one line. Phase 4. No new table.
- Backup and restore are written in the operations note and have not been drilled. Phase 5.
- No engagement store, no cost ledger, no second model provider.
- No central tool-permission registry. That is intentional until Phase 3, and Phase 3 does not add a framework.

## Tests executed

22 Nov 2026, `.venv/bin/python -m unittest` on the CEO, company, desk, and mail modules listed in `ENAAM_TEST_STRATEGY.md`.

117 tests. 115 passed. 2 errors, both in `tests/test_chief_of_staff_coverage.py`. Those tests patched `MarkdownFileNotifier` on `llm_agent` and `ask`. Those modules call `daily_brief_notifier` instead. The patches now target that function.

Re-run of `tests.test_chief_of_staff_coverage`: 15 tests, OK. The earlier traceback lines about a failed skill named `boom` and unwritable open loops are the cases those tests provoke on purpose.

Phase 3, 22 Nov 2026: `unittest discover -s tests` ran 133 tests, OK, before and after the publish gate. Coverage of the gate files: `manager.py` 100%, `action_executor.py` 96%, `llm_agent.py` 96%. `skill_context.py` is 58% because older unused helpers are untested. The new publish refusal in that file is covered.

Phase 4, 22 Nov 2026: the same suite ran 133 tests before the morning-line change and 135 after, OK.

## Known defects

- Restart is required before the desk serves new code, and it signs the owner out.
- Search again will not offer a company that was already queued.
- One password protects the whole database.

## Security limitations

See `ENAAM_SECURITY_MODEL.md`. Permissions are code, not a registry. Clients are not partitioned. New CEO turns are stored apart from the Chief of Staff transcript. Older CEO turns already in `hey-eman` remain in that session.

## Deployment readiness

The laptop process on port 8510 is the daily desk. Railway is a Dockerfile plus a volume at `/data`. Readiness means the volume has the database you intend, the environment variables are set, and a restore copy exists. Starting the process is not that check. A restore has not been drilled.

## Deviations from the directive

The directive's extra agents, task state machine, model gateway, and client CRM are not built. The skills, commitments, pending actions, and the biller list already do those jobs for a single owner. Adding parallel systems would be a second product.
