# Enaam current state

This phase is closed. The next phase has not started. Remote is `c40b8fd` on `cleanup/codebase-fixes` (`c40b8fd4e57058ea8a58871c90e781ecb62ae887`, "Judge brief items from the stored message, then from the business context."). `git log -1` and `git status -sb` showed HEAD and `origin/cleanup/codebase-fixes` at that commit.

The daily brief classifies mail from the stored sender, subject, and snippet. A sale or discount is promotional even with a deadline. Account harm is a priority alert and stays unverified. A request counts only with a deadline. Statement, credits, documents, important, and available do not qualify alone. The biller list, profile, and commitments only order or filter. They do not change that class. Recommendations are at most three. A discovery is not a commitment until the owner approves. New company notes can include a recipient found on a public page. Saved notes were not rewritten. Approve still does not send.

Not in this phase: no model classifier, no new table, no client store, no Railway database copy. The laptop process on 8510 was not restarted as part of this note.

Tests at close: 206 passed before `c40b8fd`. That is the count reported for that commit. This note does not record a new run.

The daily app is `hey_eman_app.py`. It is Streamlit, started from `.venv`, and `main` binds port 8510. One process opens one SQLite file, `khursheed.db` (`Manager` default; `KHURSHEED_DB_PATH` overrides it). `hey_eman_app.py` does not import the `enaam/` package. `enaam_ui.py`, `enaam_admin.py`, `enaam_skill_api.py`, and `enaam/mcp_server.py` are still in the tree. They are the older stack, not the daily app.

## What the desk is now

`main` builds one `Manager`, then `register_default_skills` in `skills_bootstrap.py` registers the skill classes already in that file. Those classes are the agents. Echo, timestamp, calculator, weather, file analyzer, and scout stay registered leftovers. The live jobs are the existing skills `sifter`, `icp_finder`, `icp_prospector`, `outreach_draft`, `lead_scout`, `cto_radar`, `calendar_prep`, `blogger`, and `ceo_advisor`.

Ask Enaam stores turns in two sessions. `SESSION_ID` is `hey-eman`. `CEO_SESSION_ID` is `hey-eman-ceo`. `_answer` sends a skill request to `hey-eman`. It sends "track this", a decision lookup, and a strategic question to `hey-eman-ceo`. An operational question goes to `HeyEmanAgent.respond` on `hey-eman`. `_desk_turns` shows both sessions on Ask Enaam. The Chief of Staff model loads only the session it was given.

The pages are Ask Enaam, Now, Companies, Mail, Content, and Task log. Config is the sidebar. The bills and subscriptions list is `_render_billers`, inside the scrolling Config settings, directly under "Days of mail to scan". Mail and Now show results.

Work that needs a person waits in `pending_actions`. `approve_and_execute` in `action_executor.py` is the approval path. Model calls go through `desk_model.call_model`. The desk opens with one `KHURSHEED_UI_PASSWORD`.

## Features that work

Mail and bills. `SifterSkill` reads mail and leaves bills, notices, and renewals as pending actions on Mail. The owner can mark a bill paid, leave it, mark it not a bill, or press Remember sender. `_remember_sender` calls `add_biller` and sends nothing. The bills list in Config teaches the filter which domains to keep reading. Mail and Now do not hold that list.

Companies and notes. `IcpFinderSkill` offers companies onto Companies as `icp_candidate` rows. `_own_website` keeps an address only when the host names that company. `_drop_shared_sites` blanks a URL shared by more than one name in the same offer. Search again does not offer a company that was already queued. A website already saved on a queued company stays until that company is skipped. An approved company note stays under Kept notes. `decide_icp_draft` and `track_company_note` set `sent` to false. `OutreachDraftSkill` writes a note onto Now with `send` false. Approving that note does not send it.

CEO decisions. `CeoAdvisorSkill` is the existing `ceo_advisor` skill, not a new agent. `_ask_ceo` calls `Manager.run_skill("ceo_advisor", ...)`. `_parse_model_json` accepts only JSON whose decision is `GO`, `CONDITIONAL GO`, `DEFER`, or `NO-GO`, and only when both rationales are present. Prose, broken JSON, and JSON without that decision return "CEO Advisor did not reach a decision." and `save_decision` is not called. A valid assessment is stored in `strategic_decisions` and shown as advice. The skill does not send or spend. "Track this" calls `track_latest_advice` and records the turn in `hey-eman-ceo`.

Commitments. `add_commitment` stores a promise on the existing `commitments` table with status `open`. Now lists `open` and `blocked` rows and offers Done, Blocked, and Cancelled, which call `complete_commitment`, `block_commitment`, and `cancel_commitment`. Allowed statuses are `open`, `done`, `blocked`, and `cancelled`. Done and cancelled stay as they are. A row waiting for approval is a pending action, not one of these statuses.

Morning line. Now prints `morning_focus` lines. A kept role with no date says to set a date and pauses new-name research. A dated role leads with "Follow up" or "Next follow-up". An open commitment due today or earlier adds "Commitment due" or "Commitment overdue". A blocked commitment due today or earlier adds "Blocked commitment due" or "Blocked commitment overdue". A blank due date stays off those lines. A subject whose latest stored decision is `CONDITIONAL GO` adds "Conditional decision". Lines appear only when those rows exist.

Content and the publish gate. `BloggerSkill` drafts a LinkedIn post and leaves it pending on Content. `unapproved_publish` refuses `run_skill` for `blogger` when `mode` is `publish`, including a call from another skill, and records status `refused`. The message is "Publishing waits for approval on Content. Nothing was posted." Approve on Content calls `approve_and_execute`. That path posts only a `linkedin_post_draft`, and only when `KHURSHEED_BLOGGER_PUBLISH_ENABLED` is true and the LinkedIn credentials are set. Otherwise the draft stays pending. `revise_action_payload` returns an already approved action to `pending` when the payload changes. The theme button sets `mode` to `draft`.

Task log and tokens. Task log lists `skill_runs` from the last 30 days through `_recent_runs` and `_run_line`. A run whose status is not `completed` shows that status, `execution_time_ms` when present, and up to 200 characters of the error. A completed run stays one line. When the run recorded usage, the line adds the model name, prompt tokens, and completion tokens. `Manager._record_run` writes `model`, `prompt_tokens`, and `completion_tokens` from `SkillRunUsage.recorded`. A run that never called the model stores nulls. `call_model` adds usage only inside `skill_run_usage`. A chat turn outside a skill run is not a `skill_runs` row. Counts are tokens. There is no dollar amount.

Skill limits. `skill_declarations.DECLARATIONS` names each live skill's side effect and max model calls. `declaration_refusal` runs in `Manager.run_skill` and `SkillContext.run_skill`, beside the publish refusal. A payload whose `model_calls` is above the maximum is refused and the skill is not called. Omitting `model_calls` leaves the skill's own calls alone. A skill cannot run an external skill. `blogger` is the external one. `caller == "ceo_advisor"` is refused with "The CEO skill does not run another skill." `HeyEmanAgent._run_tool_loop` stops after four tool steps. The catalog states there is no shared token budget. The maxima are `icp_finder` 1, `cto_radar` 0, `lead_scout` 0, `icp_prospector` 2, `outreach_draft` 0, `sifter` 100, `calendar_prep` 0, `blogger` 1, `ceo_advisor` 2.

## Design choices that replaced the directive's new systems

Separate CoS and CEO sessions. New Chief of Staff turns stay in `hey-eman`. New CEO assessments, decision lookups, and "track this" are stored in `hey-eman-ceo`. Ask Enaam shows both. Older CEO rows already in `hey-eman` are left there.

Specialized agents. No new agent classes were added. The jobs are the skills named in `skills_bootstrap.py` and described in `docs/ENAAM_AGENT_CATALOG.md`.

Model-provider abstraction. `desk_model.call_model` is one function in the working tree. `DEFAULT_MODEL` is `gpt-4o-mini`. `configured_model` reads `KHURSHEED_MODEL` and keeps `gpt-4o-mini` when that value is blank. `provider_for` returns `openai` for `gpt-4o-mini`. It returns `anthropic` only when the name is a Claude model and `ANTHROPIC_API_KEY` is set. Any other name raises `ModelSelectionError` before a client is built. `HeyEmanAgent` passes `model=None` so the same rule applies, and it returns that error as the reply. `desk_model.py` is on the remote at `c40b8fd`. The recovery note still says the directive's model gateway is not built. This phase adds no model classifier.

Task state machine. Commitment status lives on the existing `commitments` table. Approval state lives on `pending_actions`. There is no second task table.

Tool permission registry. There is no registry. `unapproved_publish` and `declaration_refusal` are checks in `run_skill`. Leftover skills are registered and are not in `DECLARATIONS`.

Approval center. There is no separate approval app. Now, Companies, Mail, and Content render `pending_actions`. Content is the publish path. `approve_and_execute` finishes an approved row.

Token and cost tracking. `skill_runs` stores the model name and token counts for a skill run. The task log prints those counts. There is no price table and no cost ledger.

Eval suite. `tests/test_enaam_eval.py` is the desk eval. Its five methods check that a strategic question writes `hey-eman-ceo` and does not call `HeyEmanAgent.respond`, that a model tool call cannot publish, that a directory page is not stored as a company website, that invalid CEO JSON is not stored, and that a commitment can move to `blocked` and `cancelled`. The fake model does not call a paid API. The file is on the remote at `c40b8fd`.

IDPETECH client store. There is no client engagement table. `docs/ENAAM_TEST_STRATEGY.md` says cross-client retrieval waits until engagements exist. `docs/ENAAM_IMPLEMENTATION_STATUS.md` says clients are not partitioned.

Backup and restore. The steps are in `docs/ENAAM_OPERATIONS_RUNBOOK.md`, committed in `834caa3`. The laptop file and Railway `/data/khursheed.db` stay two databases. On 22 Nov 2026 a temporary laptop copy returned `integrity_check` `ok` and was deleted. The live file was not replaced. The Railway volume was not copied. No off-machine copy is kept. The replacement was not performed.

Gaps, stated from the code and the status note: no client engagement table, no dollar prices, no new agent classes, historical CEO rows left in `hey-eman`, one shared password (`KHURSHEED_UI_PASSWORD`), directory websites already saved are not rewritten, restore has been written and a laptop copy was checked then deleted, no off-machine copy is kept, and the replacement was not performed.

## What changed after the directive

This phase is closed. The next phase has not started. Remote `cleanup/codebase-fixes` is `c40b8fd` (`c40b8fd4e57058ea8a58871c90e781ecb62ae887`, "Judge brief items from the stored message, then from the business context."). `git status -sb` shows the branch level with `origin/cleanup/codebase-fixes`.

Pushed history through that commit includes the JSON CEO decision and kept company notes (`23dd2c8`), the bills list kept in Config (`d14a3e0`), the CEO session split (`c000527`), the publish refusal (`350b6ab`), the morning line for a due commitment and a conditional decision (`fd95e1a`), the rule that a list page is not stored as a company website (`e09c346`), the recovery steps (`834caa3`), model calls, skill limits, and commitment states (`974cdec`), icon labels (`c0daaba`), and the brief rules (`c40b8fd`). `4c5898d` hid a saved list page and `661f57a` reverted that commit. Saved notes were not rewritten.

206 passed before `c40b8fd`. That is the count reported for the commit. This note does not record a new run.

## How to verify

The command is `.venv/bin/python -m unittest discover -s tests -t .`. The count reported for `c40b8fd` is 206 passed, before that commit. This note does not re-run the suite.

Streamlit does not reload. The process on 8510 serves the code it was started with until it is restarted, and a restart signs the owner out. This note did not restart that process.

## Still out

No model classifier. No new table. No client store. No price table. No new agent classes. No Railway database copy. The next phase has not started. The bills list stays in Config under "Days of mail to scan". Approve still does not send.
