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
- No execution-layer permission check beyond the skill code. Phase 3.
- Morning line does not yet add due commitments and conditional CEO decisions. Task log does not yet surface a failed run's duration and error as a first-class line. Phase 4.
- Backup and restore are written in the operations note and have not been drilled. Phase 5.
- No engagement store, no cost ledger, no second model provider.
- No central tool-permission registry. That is intentional until Phase 3, and Phase 3 does not add a framework.

## Tests executed

22 Nov 2026, `.venv/bin/python -m unittest` on the CEO, company, desk, and mail modules listed in `ENAAM_TEST_STRATEGY.md`.

117 tests. 115 passed. 2 errors, both in `tests/test_chief_of_staff_coverage.py`. Those tests patched `MarkdownFileNotifier` on `llm_agent` and `ask`. Those modules call `daily_brief_notifier` instead. The patches now target that function.

Re-run of `tests.test_chief_of_staff_coverage`: 15 tests, OK. The earlier traceback lines about a failed skill named `boom` and unwritable open loops are the cases those tests provoke on purpose.

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
