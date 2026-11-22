# Desk state — 20 Nov 2026

Live desk is `hey_eman_app.py` on port 8510, branch `cleanup/codebase-fixes`.
The quarter's goal is one fractional CTO retainer. Bills already surface.
The weekly post already waits for a yes.

## Done

- Gmail `[Gmail]/All Mail` is quoted on select, so a space in the mailbox name no longer fails the scan.
- The morning leads with one dated next step on a kept role. A bill that is overdue, due today, or due within 2 days outranks that role. While any kept role has no date, or a role is waiting and nothing is kept, lead scout, CTO radar, ICP finder, and ICP prospector stay quiet. An empty desk still searches.
- The same rule is what the brief, the Telegram text, Now, and the morning run use. A kept role can store a next-step date.
- One company can be qualified from Companies. The purpose defaults to a CTO opportunity, and it can be changed before Qualify. Search again looks for new names after the current ones are handled. A fit leaves a note there until Approve or Not now. Approving records consent and does not send the note. The note stays under Kept notes, and Track follow-up puts it on Now. The morning run only finishes a company already past qualify.
- The desk pages are Ask Enaam, Now, Companies, Mail, Content, and Task log. Now holds the morning line, waiting roles, and anything that needs a decision. Companies holds the ICP names. Mail holds ordinary notices and bills. The bills and subscriptions list lives in Config, under the mail scan setting. On a phone the page names sit in a menu. The chips are need-you, companies, mail, and the brief.
- A strategic question goes to CEO Advisor before the chat model can answer it. That transcript is stored in its own session, so the chat model does not reread it. The assessment is stored, can be asked for later, and ends in GO, CONDITIONAL GO, DEFER, or NO-GO. It is advice. Saying "track this" saves only the next action and does not send, spend, or publish. The morning run does not call it.

## Left, in order

Qualify one live company from Companies before trusting that path. Then pick these up only after the dated follow-up has been the morning habit. Do the first one that becomes true.

1. Who is waiting in non-bill mail, once a client or a prospect writes often enough that a bills-only inbox misses them.
2. Meeting prep past the calendar titles, once the calendar feed is on and a meeting needs more than a time.
3. Invoices and who owes you, once someone is paying.
4. A weekly close, once the dated follow-up has held for a few weeks.
5. Richer memory than `config/principal.json`, once the same judgment is being repeated and the file cannot hold it.
6. Remove demo skills, the second scheduler, and the old Enaam tree, once the morning action is trustworthy. This is deletion, not a new feature.

The Mac morning cron was removed on 19 Nov 2026. It had been `* * * * *` running `scripts/morning_run.py`. The Monday 09:00 `weekly_summary.py` cron is still installed. On Railway the desk still loops `morning_watch.py`; that is not a cron, and it must not get one.

## Do not build

A skill factory. Another search. The old Enaam architecture, MCP server, or `scripts/start_enaam_services.sh`. A CRM, a general inbox, or a ledger. Publishing machinery beyond one weekly draft that waits for a yes. Skills that send mail or post on their own. Moving or removing the bills and subscriptions list from Config. It stays under "Days of mail to scan". Mail and Now stay results. That move needs explicit consent.
