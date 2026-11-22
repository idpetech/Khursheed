# Enaam final-state assessment

Assessed 22 Nov 2026 against the live desk. The running application is `hey_eman_app.py` (Streamlit, `.venv`, port 8510). It does not import `enaam/`. Current status is `ENAAM_IMPLEMENTATION_STATUS.md`. Code on the remote is `e09c346` on `cleanup/codebase-fixes`.

## 1. Current architecture

One Streamlit process. One `Manager`. Skills register in `skills_bootstrap.py` and run through `Manager.run_skill`. State is `khursheed.db`.

Ask Enaam classifies a question before the chat model runs. A strategic question goes to `ceo_advisor` and is stored in `hey-eman-ceo`. Operational replies stay in `hey-eman`. The CEO skill does not read chat history. `HeyEmanAgent.respond` loads the last eight turns of `hey-eman` only. Older CEO replies already stored in `hey-eman` remain visible to that model until newer operational turns push them out.

Pages: Ask Enaam, Now, Companies, Mail, Content, Task log. Config is the sidebar. The bills and subscriptions list is inside that scrolling panel, under "Days of mail to scan". Mail and Now show results only.

The older stack (`enaam_ui.py`, `enaam_admin.py`, `enaam_skill_api.py`, `enaam/`) is still in the tree. It is not the daily app.

## 2. Existing functional capabilities

- Mail scan and bill classification (`sifter`). Headers first. A body is fetched when the message is a candidate. Deduped by account, message id, and kind.
- A biller list. Domains on it are read even when the wording does not match the keyword filter. Add and Remove are in Config. Remember sender on a bill, notice, or renewal adds to that same list. Nothing is sent.
- Morning brief, priority inbox, and a research pause while a kept role has no date.
- Companies: ICP search, one-company qualify, a note that is not sent, Search again, and Kept notes.
- CEO assessment as one JSON decision (`GO`, `CONDITIONAL GO`, `DEFER`, `NO-GO`), stored in `strategic_decisions`. Tavily excerpts are labeled as excerpts. "Track this" writes one commitment and does not send, spend, or publish.
- Commitments and pursuits. LinkedIn draft waits for a person. Publish stays behind its own flag.
- A password gate (`KHURSHEED_UI_PASSWORD`). Keys stay in the environment.

## 3. Existing reusable components

- `Skill.run(task)` and `Manager.run_skill`.
- `pending_actions` as the approval queue.
- `chat_turns` keyed by `session_id`. Chief of Staff uses `hey-eman`. New CEO turns use `hey-eman-ceo`.
- `workflow_runs` for one company at a time.
- `desk_work` commitments and pursuits.
- `billers` for domains the mail filter must always read.
- `database_migrations.py`, plus small idempotent table creates in the desk modules.
- `unittest`, with the model and search mocked.

## 4. Architectural weaknesses

- P2. Older CEO replies already stored in `hey-eman` can still sit in the Chief of Staff model's last eight turns. New CEO replies go to `hey-eman-ceo`.
- P1. Model calls are direct `openai` uses of `gpt-4o-mini`. There is no second provider, and none is justified yet.
- P2. `hey_eman_app.py` holds the pages, the router, and the review buttons. Streamlit does not reload code until the process is restarted, which signs the owner out.
- P2. Schema changes use both numbered migrations and `CREATE TABLE IF NOT EXISTS` inside feature modules.
- P3. The `enaam/` tree is large enough to look like the product. It is not.

## 5. Security and privacy risks

- P1. One shared password. The desk binds to `0.0.0.0`. Anyone who can reach the port and knows the password has the whole desk. There is no per-client login because clients do not use Enaam. This stays as it is.
- P1. Sending, spending, and publishing are blocked in skill code and in `action_executor`, not by a central policy object. A new skill could forget that.
- P2. Mail text can reach a model. The sifter does not send. The chat agent can call skills. Those skills do not send mail.
- P2. Logs can include a short subject. They must not include keys or mailbox bodies. That is a convention, not a filter.
- P3. No separate client vault. Advisory notes would sit in the same database as personal mail until an engagement boundary exists. That store is deferred.

## 6. Reliability and observability gaps

- P1. No token or cost ledger. A failed model call is logged. The CEO path logs duration. `skill_runs` stores `execution_time_ms`.
- P1. Backup and restore steps are in the operations note. A laptop copy checked clean and was deleted. The live file was not replaced. The Railway volume was not copied. No off-machine copy is kept.
- P2. `tests/test_chief_of_staff_coverage.py` used to patch `MarkdownFileNotifier` on modules that call `daily_brief_notifier`. Those two patches now target `daily_brief_notifier`. The module's 15 tests pass.
- P2. No watchdog. A code change is invisible until restart.

## 7. Missing capabilities

Counted only where the desk does not already do the job.

- P2. Historical CEO turns already in `hey-eman` are not moved. New ones are separate.
- P2. Advisory engagements are not a stored, isolated context. Deferred. `DESK_STATE.md` says not to build a CRM.
- P2. Tasks are commitments, pursuits, and pending actions. A second task state machine would duplicate them.
- P3. Extra agent classes and a second model provider. The skills already cover the jobs. OpenAI is the provider in use.

## 8. Recommended target architecture

Keep the current shape.

- One process, one SQLite file, one `Manager`.
- Chief of Staff session `hey-eman`. CEO session `hey-eman-ceo`. Shared facts come from tables, not from the other transcript.
- Skills remain the tools. Approval remains `pending_actions`.
- The bills and subscriptions list stays in Config, under "Days of mail to scan". Mail and Now stay results. Moving or removing that list needs explicit consent.
- Do not import `enaam/`. Do not add Hermes, Supabase, Redis, or Postgres.

## 9. Prioritized backlog

1. P2. Leave historical CEO rows in `hey-eman`. Do not rewrite them.
2. P1. Keep an off-machine copy of `khursheed.db`. The steps are written. The replacement itself has not been performed.
3. P2. Leave client isolation until a second client is real.
4. P3. Do not add providers, agents, or a task schema until a current skill cannot do the job.

## 10. Risks and migration

- Splitting sessions must leave existing `hey-eman` rows in place, including older CEO answers.
- `skill_runs`, commitments, bills, billers, and `strategic_decisions` stay. No row is deleted for this work.
- Restarting Streamlit signs the owner out. The password is not stored in the repo.
