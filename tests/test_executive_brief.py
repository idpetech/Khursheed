"""Classification, score, and deduped brief. No network."""

import json
import sqlite3
import tempfile
import unittest
from datetime import date
from datetime import datetime
from pathlib import Path

from briefing import approve_brief_commitment
from briefing import classify_item
from briefing import dedupe_items
from briefing import dismiss_brief_item
from briefing import format_open_commitments
from briefing import prepare_items
from briefing import render_item
from desk_work import list_commitments
from desk_work import morning_focus
from executive_summary import generate_executive_summary
from manager import Manager


TODAY = date(2026, 11, 19)
WHEN = "2026-11-18T15:00:00+00:00"

WAREHOUSE = {
    "title": "Fractional advisor for warehouse WMS and ERP integration",
    "url": "https://northwind.example/advisory",
    "snippet": (
        "Remote United States consulting engagement for a B2B SaaS supply-chain company. "
        "Strategic advisory and part-time architecture decisions, not a full-time operating role."
    ),
    "company": "Northwind Logistics",
}

FULL_TIME = {
    "title": "Full-time CTO",
    "url": "https://jobs.example.com/roles/cto",
    "snippet": (
        "Generic software job. Own the engineering organization. "
        "Daily availability required on site."
    ),
}


class _Silent:
    def send(self, content: str) -> str:
        return "ok"


def _run(skill: str, result: dict, executed_at: str = WHEN) -> dict:
    return {"skill_name": skill, "executed_at": executed_at, "result_json": result}


def _insert_run(db_path: str, skill: str, result: dict, executed_at: str = WHEN) -> None:
    Manager(db_path=db_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO skill_runs (
                run_id, task_id, skill_name, executed_at, result_json, status, created_at
            ) VALUES (?, ?, ?, ?, ?, 'completed', ?)
            """,
            (f"{skill}-{executed_at}-{result.get('marker', skill)}", skill, skill, executed_at, json.dumps(result), executed_at),
        )


def _count(db_path: str, table: str) -> int:
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table,),
        ).fetchone()
        if not row:
            return 0
        return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


class BriefingTests(unittest.TestCase):
    def test_duplicate_job_across_skills_is_shown_once(self):
        title = "CTO at Northwind Logistics"
        url = "https://jobs.northwind.example/cto"
        snippet = "Fractional CTO opening. Remote United States. Advisory for a B2B SaaS warehouse team."
        runs = [
            _run(
                "lead_scout",
                {"queries": [{"leads": [{"title": title, "url": url + "?utm_source=newsletter", "snippet": snippet}]}]},
            ),
            _run(
                "cto_radar",
                {"opportunities": [{"title": title, "url": "https://www.jobs.northwind.example/cto/", "snippet": snippet}]},
            ),
        ]
        loops = [
            {
                "title": title,
                "source": "cto_radar",
                "source_key": f"cto:{url}",
                "detail": snippet,
                "created_at": WHEN,
            }
        ]
        collected_runs = list(runs)
        merged = prepare_items(collected_runs, loops)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["raw_count"], 3)
        self.assertEqual(len(runs), 2)
        self.assertIn("lead_scout", merged[0]["sources"])
        self.assertIn("cto_radar", merged[0]["sources"])
        self.assertTrue(any("2026-11-18" in stamp for stamp in merged[0]["discovered"]))
        text = render_item(merged[0])
        self.assertEqual(text.count("https://"), 1)

    def test_duplicate_company_is_shown_once(self):
        rationale = "Series A B2B SaaS company. No full-time CTO is mentioned. Exploring advisory help."
        runs = [
            _run(
                "icp_prospector",
                {"top_companies": [{"company_name": "Fintechly", "industry": "fintech", "rationale": rationale}]},
            ),
            _run(
                "lead_scout",
                {
                    "queries": [
                        {
                            "leads": [
                                {
                                    "title": "Advisor at Fintechly",
                                    "url": "https://news.example/fintechly",
                                    "snippet": rationale,
                                    "company": "Fintechly",
                                }
                            ]
                        }
                    ]
                },
            ),
        ]
        merged = prepare_items(runs, [])
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["raw_count"], 2)
        self.assertEqual(merged[0]["company_key"], "fintechly")
        self.assertIn("icp_prospector", merged[0]["sources"])
        self.assertIn("lead_scout", merged[0]["sources"])

    def test_classification_uses_one_class_and_unknown_when_thin(self):
        warehouse = score_item_from_role(WAREHOUSE)
        self.assertEqual(warehouse["classification"], "engagement")
        partner = prepare_items(
            [
                _run(
                    "lead_scout",
                    {
                        "queries": [
                            {
                                "leads": [
                                    {
                                        "title": "Fractional CTO marketplace",
                                        "url": "https://partners.example/marketplace",
                                        "snippet": (
                                            "A marketplace and referral partner directory for independent CTOs. "
                                            "This is a channel for introductions."
                                        ),
                                    }
                                ]
                            }
                        ]
                    },
                )
            ],
            [],
        )[0]
        self.assertEqual(partner["classification"], "partner")
        competitor = prepare_items(
            [
                _run(
                    "lead_scout",
                    {
                        "queries": [
                            {
                                "leads": [
                                    {
                                        "title": "Harbor Advisory",
                                        "url": "https://harbor.example/services",
                                        "snippet": (
                                            "We provide fractional CTO services to seed-stage software companies. "
                                            "Book a call with our team."
                                        ),
                                    }
                                ]
                            }
                        ]
                    },
                )
            ],
            [],
        )[0]
        self.assertEqual(competitor["classification"], "competitor")
        prospect = prepare_items(
            [
                _run(
                    "icp_prospector",
                    {
                        "top_companies": [
                            {
                                "company_name": "Brightline",
                                "industry": "saas",
                                "funding_stage": "series-a",
                                "rationale": "B2B SaaS company in the stored seed. Industry and stage were stored. Nothing further was stated.",
                            }
                        ]
                    },
                )
            ],
            [],
        )[0]
        self.assertEqual(prospect["classification"], "prospect")
        self.assertTrue(prospect["icp_only"])
        research = prepare_items(
            [
                _run(
                    "lead_scout",
                    {
                        "queries": [
                            {
                                "leads": [
                                    {
                                        "title": "What is a fractional CTO",
                                        "url": "https://www.youtube.com/watch?v=abc",
                                        "snippet": "A video overview of technology leadership. Not an open role.",
                                    }
                                ]
                            }
                        ]
                    },
                )
            ],
            [],
        )[0]
        self.assertEqual(research["classification"], "research")
        unknown = prepare_items(
            [_run("lead_scout", {"queries": [{"leads": [{"title": "Note", "url": "", "snippet": "Hello"}]}]})],
            [],
        )[0]
        self.assertEqual(unknown["classification"], "unknown")
        self.assertEqual(classify_item(unknown), "unknown")

    def test_warehouse_consulting_scores_high_and_full_time_engagement_is_low(self):
        warehouse = score_item_from_role(WAREHOUSE, "2026-11-18T15:00:00+00:00")
        self.assertGreaterEqual(warehouse["score"], 80)
        self.assertEqual(warehouse["band"], "high")
        self.assertEqual(sum(warehouse["factors"].values()), warehouse["score"])
        full_time = score_item_from_role(FULL_TIME, "2026-11-18T15:00:00+00:00")
        self.assertLessEqual(full_time["factors"]["engagement_compatibility"], 5)
        self.assertEqual(full_time["band"], "low")
        self.assertIn("Job listing, not a consulting service page.", render_item(full_time))

    def test_weak_evidence_lowers_confidence_and_is_not_a_confirmed_lead(self):
        strong = score_item_from_role(WAREHOUSE, WHEN)
        weak = score_item_from_role(
            {
                "title": WAREHOUSE["title"],
                "url": "",
                "snippet": "",
                "company": "",
            },
            "",
        )
        self.assertLess(weak["confidence"], strong["confidence"])
        self.assertLess(weak["factors"]["evidence_credibility"], strong["factors"]["evidence_credibility"])
        text = render_item(weak) + "\n" + render_item(strong)
        self.assertNotIn("confirmed lead", text.lower())
        self.assertNotIn("confirmed open", text.lower())
        self.assertIn("Evidence is thin.", render_item(weak))

    def test_unverified_link_is_flagged(self):
        item = score_item_from_role(WAREHOUSE, WHEN)
        text = render_item(item)
        self.assertIn("Link not verified.", text)
        self.assertNotIn("confirmed open", text.lower())
        self.assertNotIn("live posting", text.lower())
        self.assertNotIn("verified business", text.lower())
        self.assertFalse(item["link_verified"])

    def test_model_company_name_is_an_assessment(self):
        item = prepare_items(
            [
                _run(
                    "icp_finder",
                    {
                        "candidates": [
                            {
                                "company_name": "Example Works",
                                "website": "https://example-works.example",
                                "why": "The search text names Example Works as a B2B SaaS company that might want advisory help.",
                            }
                        ]
                    },
                )
            ],
            [],
        )[0]
        text = render_item(item)
        self.assertIn("Assessment:", text)
        self.assertIn("not verified as a business", text)
        self.assertNotIn("verified business", text.lower())

    def test_discovery_does_not_insert_a_commitment_until_approval(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "t.db")
            Manager(db_path=db_path)
            _insert_run(
                db_path,
                "cto_radar",
                {"opportunities": [{**WAREHOUSE, "marker": "one"}]},
            )
            before = _count(db_path, "commitments")
            prepare_items(
                [_run("cto_radar", {"opportunities": [WAREHOUSE]})],
                [],
            )
            generate_executive_summary(Manager(db_path=db_path), _Silent(), now=datetime(2026, 11, 19, 8, 0))
            morning_focus(db_path, TODAY)
            self.assertEqual(_count(db_path, "commitments"), before)
            self.assertEqual(list_commitments(db_path), [])
            scored = score_item_from_role(WAREHOUSE, WHEN)
            saved = approve_brief_commitment(db_path, scored["item_key"], scored["title"], "2026-11-18")
            self.assertEqual(saved["status"], "ok")
            self.assertEqual(_count(db_path, "commitments"), before + 1)
            self.assertEqual(list_commitments(db_path)[0]["title"], scored["title"])
            prepare_items([_run("cto_radar", {"opportunities": [WAREHOUSE]})], [])
            morning_focus(db_path, TODAY)
            self.assertEqual(_count(db_path, "commitments"), before + 1)

    def test_historical_rows_remain_after_dedupe(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "t.db")
            _insert_run(
                db_path,
                "lead_scout",
                {"marker": "a", "queries": [{"leads": [{**WAREHOUSE, "url": "https://jobs.northwind.example/cto?utm_source=a"}]}]},
            )
            _insert_run(
                db_path,
                "cto_radar",
                {"marker": "b", "opportunities": [{**WAREHOUSE, "url": "https://www.jobs.northwind.example/cto/"}]},
            )
            before = _count(db_path, "skill_runs")
            self.assertEqual(before, 2)
            from briefing import _read_runs

            runs = _read_runs(db_path, "2020-01-01T00:00:00+00:00")
            merged = dedupe_items_from_runs(runs)
            self.assertEqual(len(merged), 1)
            self.assertEqual(_count(db_path, "skill_runs"), before)
            self.assertEqual(len(runs), before)

    def test_done_and_cancelled_commitments_stay_off_and_suggestion_does_not_repeat(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "t.db")
            _insert_run(db_path, "cto_radar", {"opportunities": [WAREHOUSE], "marker": "suggest"})
            first = morning_focus(db_path, TODAY)
            self.assertTrue(any(line.startswith("Suggestion, not a commitment:") for line in first["lines"]))
            self.assertEqual(_count(db_path, "commitments"), 0)
            second = morning_focus(db_path, TODAY)
            self.assertFalse(any(line.startswith("Suggestion, not a commitment:") for line in second["lines"]))
            self.assertIn("No kept role yet.", second["lines"])
            scored = score_item_from_role(WAREHOUSE, WHEN)
            approve_brief_commitment(db_path, scored["item_key"], "Send the warehouse note", "2026-11-18")
            from desk_work import cancel_commitment
            from desk_work import complete_commitment

            open_row = list_commitments(db_path)[0]
            shown = format_open_commitments(list_commitments(db_path, ("open", "blocked")), TODAY)
            self.assertIn("past due", shown)
            self.assertIn("Send the warehouse note", shown)
            complete_commitment(db_path, open_row["commitment_id"])
            hidden = format_open_commitments(
                list_commitments(db_path, ("open", "blocked", "done", "cancelled")),
                TODAY,
            )
            self.assertNotIn("Send the warehouse note", hidden)
            other = approve_brief_commitment(db_path, "company:other", "Call the other firm", "2026-11-01")
            cancel_commitment(db_path, other["commitment_id"])
            hidden_again = format_open_commitments(
                list_commitments(db_path, ("open", "blocked", "done", "cancelled")),
                TODAY,
            )
            self.assertNotIn("Call the other firm", hidden_again)
            dismiss_brief_item(db_path, "company:fintechly", "Fintechly")
            self.assertEqual(
                [row["title"] for row in list_commitments(db_path)],
                [],
            )


def score_item_from_role(row: dict, found: str = WHEN) -> dict:
    item = prepare_items([_run("cto_radar", {"opportunities": [row]}, found)], [])[0]
    return item


def dedupe_items_from_runs(runs: list[dict]) -> list[dict]:
    from briefing import collect_discovered

    collected = collect_discovered(runs, [])
    return dedupe_items(collected)


def _section(report: str, title: str) -> str:
    marker = f"## {title}"
    if marker not in report:
        return ""
    body = report.split(marker, 1)[1]
    if "\n## " in body:
        body = body.split("\n## ", 1)[0]
    return body.strip()


def _headings(report: str) -> list[str]:
    return [line[3:].strip() for line in report.splitlines() if line.startswith("## ")]


class BriefRecordTests(unittest.TestCase):
    """Counts and wording come from stored rows. No network and no live mail."""

    def _db(self) -> str:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        db_path = str(Path(self._tmpdir.name) / "t.db")
        Manager(db_path=db_path)
        return db_path

    def _report(self, db_path: str, day: date = date(2026, 11, 22)) -> str:
        return generate_executive_summary(
            Manager(db_path=db_path),
            _Silent(),
            now=datetime(day.year, day.month, day.day, 8, 0),
        )

    def test_sample_sections_keep_alerts_bills_and_research_apart(self):
        from open_loops import emit_open_loop
        from priority_inbox import emit_priority_action

        db_path = self._db()
        emit_priority_action(
            kind="renewal_notice",
            title="Subscription deactivation warning",
            description="Subscription deactivation warning",
            payload={
                "from": "Jira <billing@atlassian.example>",
                "subject": "Subscription deactivation warning",
                "sent_at": "2026-11-15T12:00:00+00:00",
                "account": "desk",
            },
            priority=2,
            source_key="notice-jira",
            db_path=db_path,
        )
        emit_priority_action(
            kind="new_bill",
            title="AT&T bill",
            description="AT&T bill",
            payload={
                "vendor": "AT&T",
                "amount": "418.13",
                "currency": "USD",
                "due_date": "2026-12-10",
                "from": "AT&T <bill@att.example>",
                "subject": "Your bill is ready",
                "sent_at": "2026-11-16T12:00:00+00:00",
            },
            priority=1,
            source_key="bill-att",
            db_path=db_path,
        )
        emit_open_loop(
            "cto_radar",
            "cto:https://www.indeed.com/jobs?q=fractional+cto",
            "Fractional CTO jobs",
            detail="Saved search page for fractional CTO roles.",
            db_path=db_path,
        )
        emit_open_loop(
            "lead_scout",
            "lead:https://www.youtube.com/watch?v=abc",
            "What is a fractional CTO",
            detail="A youtube overview. Not an open role.",
            db_path=db_path,
        )
        report = self._report(db_path)
        self.assertEqual(
            _headings(report),
            [
                "Executive Focus",
                "Priority Attention",
                "Research and Opportunities",
                "Open Commitments",
                "Recommended Actions",
            ],
        )
        focus = _section(report, "Executive Focus")
        attention = _section(report, "Priority Attention")
        research = _section(report, "Research and Opportunities")
        commitments = _section(report, "Open Commitments")
        actions = _section(report, "Recommended Actions")
        self.assertIn("Verify Jira subscription status.", focus)
        self.assertIn("Review the upcoming AT&T bill.", focus)
        self.assertIn("No qualified fractional CTO engagement has yet been established.", focus)
        self.assertNotIn("No action is justified", focus)
        self.assertNotIn("unpaid", focus.lower())
        self.assertNotIn("overdue", focus.lower())
        self.assertNotIn("about to be deactivated", report.lower())
        self.assertIn("Subscription deactivation warning", attention)
        self.assertIn("Original email received November 15.", attention)
        self.assertIn("From Jira <billing@atlassian.example>.", attention)
        self.assertIn("Current status unverified", attention)
        self.assertIn("requiring verification", attention)
        self.assertIn("AT&T: $418.13 due December 10.", attention)
        self.assertIn("Payment status unverified.", attention)
        self.assertIn("From AT&T <bill@att.example>.", attention)
        self.assertIn("Subject: Your bill is ready.", attention)
        self.assertNotIn("unpaid", attention.lower())
        self.assertNotIn("overdue", attention.lower())
        self.assertEqual(research.lower().count("fractional cto market"), 1)
        self.assertIn("consolidated into one research topic", research)
        self.assertIn("No confirmed high-priority engagement identified.", research)
        self.assertNotIn("- Fractional CTO jobs", research)
        self.assertNotIn("- What is a fractional CTO", research)
        self.assertEqual(commitments, "None.")
        self.assertNotIn("Jira", commitments)
        self.assertNotIn("AT&T", commitments)
        self.assertIn("Verify Jira subscription status.", actions)
        self.assertIn("Review AT&T bill before December 10.", actions)
        self.assertIn(
            "Continue fractional CTO research only when a specific, credible opportunity appears.",
            actions,
        )
        self.assertLessEqual(len([line for line in actions.splitlines() if line.strip()]), 3)
        self.assertNotIn("not a commitment", actions.lower())
        self.assertEqual(_count(db_path, "commitments"), 0)

    def test_priority_alert_and_bill_are_not_open_commitments(self):
        from briefing import brief_counts
        from priority_inbox import emit_priority_action

        db_path = self._db()
        emit_priority_action(
            kind="mail_notice",
            title="Pager",
            description="Pager",
            payload={"from": "Ops <ops@example.com>", "subject": "Backup needs a look. Please confirm by December 1.", "sent_at": "2026-11-01"},
            priority=3,
            source_key="alert-pager",
            db_path=db_path,
        )
        emit_priority_action(
            kind="new_bill",
            title="Host",
            description="Host",
            payload={"vendor": "Host", "amount": "10", "currency": "USD", "due_date": "2026-12-01"},
            priority=2,
            source_key="bill-host",
            db_path=db_path,
        )
        report = self._report(db_path)
        counts = brief_counts(db_path)
        self.assertEqual(counts["priority_alerts"], 1)
        self.assertEqual(counts["pending_bills"], 1)
        self.assertEqual(counts["open_commitments"], 0)
        self.assertIn("Priority alerts: 1.", report)
        self.assertIn("Pending bills: 1.", report)
        self.assertIn("Outstanding commitments: 0.", report)
        self.assertNotIn("Outstanding actions:", report)
        commitments = _section(report, "Open Commitments")
        self.assertEqual(commitments, "None.")
        self.assertNotIn("Pager", commitments)
        self.assertNotIn("Backup needs a look", commitments)
        self.assertNotIn("Host", commitments)
        self.assertIn("Backup needs a look", _section(report, "Priority Attention"))
        self.assertIn("Host", _section(report, "Priority Attention"))

    def test_recommendation_is_not_an_outstanding_commitment(self):
        db_path = self._db()
        _insert_run(db_path, "cto_radar", {"opportunities": [WAREHOUSE], "marker": "suggest"})
        report = self._report(db_path, TODAY)
        self.assertIn("Suggestion, not a commitment:", report)
        self.assertEqual(_section(report, "Open Commitments"), "None.")
        self.assertEqual(_count(db_path, "commitments"), 0)
        self.assertIn("Outstanding commitments: 0.", report)

    def test_a_saved_search_page_is_not_an_open_loop(self):
        from briefing import loop_is_explicit_action
        from open_loops import emit_open_loop

        db_path = self._db()
        emit_open_loop(
            "cto_radar",
            "cto:https://www.indeed.com/q-fractional-cto.html",
            "Now Hiring: 40 Fractional CTO jobs",
            detail="Broad job search results. No single company named.",
            db_path=db_path,
        )
        loop = {
            "title": "Now Hiring: 40 Fractional CTO jobs",
            "source_key": "cto:https://www.indeed.com/q-fractional-cto.html",
            "detail": "Broad job search results.",
        }
        self.assertFalse(loop_is_explicit_action(loop))
        report = self._report(db_path)
        self.assertNotIn("## Open Loops", report)
        self.assertEqual(_section(report, "Open Commitments"), "None.")
        self.assertIn("Fractional CTO market", _section(report, "Research and Opportunities"))
        self.assertEqual(_count(db_path, "commitments"), 0)

    def test_related_search_pages_are_one_research_topic(self):
        from open_loops import emit_open_loop

        db_path = self._db()
        emit_open_loop(
            "cto_radar",
            "cto:https://www.linkedin.com/jobs/search?keywords=fractional%20cto",
            "Fractional CTO jobs in the United States",
            detail="Saved search page.",
            db_path=db_path,
        )
        emit_open_loop(
            "lead_scout",
            "lead:https://youtu.be/xyz",
            "Fractional CTO marketplace tour",
            detail="A youtube page and a broad marketplace listing.",
            db_path=db_path,
        )
        report = self._report(db_path)
        research = _section(report, "Research and Opportunities")
        self.assertEqual(research.lower().count("fractional cto market"), 1)
        self.assertIn("consolidated into one research topic", research)
        self.assertNotIn("## Open Loops", report)

    def test_stale_alert_requires_verification_and_a_future_bill_is_not_overdue(self):
        from priority_inbox import emit_priority_action

        db_path = self._db()
        emit_priority_action(
            kind="renewal_notice",
            title="Subscription deactivation warning",
            description="Subscription deactivation warning",
            payload={
                "from": "Jira <billing@atlassian.example>",
                "subject": "Subscription deactivation warning",
                "sent_at": "Sun, 15 Nov 2026 12:00:00 +0000",
            },
            priority=3,
            source_key="stale-jira",
            db_path=db_path,
        )
        emit_priority_action(
            kind="new_bill",
            title="AT&T",
            description="AT&T",
            payload={"vendor": "AT&T", "amount": 418.13, "currency": "USD", "due_date": "2026-12-10"},
            priority=1,
            source_key="future-att",
            db_path=db_path,
        )
        report = self._report(db_path)
        attention = _section(report, "Priority Attention")
        self.assertIn("requiring verification", attention)
        self.assertIn("Current status unverified", attention)
        self.assertIn("November 15", attention)
        self.assertNotIn("will be deactivated", report.lower())
        self.assertNotIn("about to be deactivated", report.lower())
        self.assertIn("upcoming", _section(report, "Executive Focus"))
        self.assertNotIn("overdue", report.lower())
        self.assertNotIn("unpaid", report.lower())
        self.assertNotIn("No action is justified", _section(report, "Executive Focus"))

    def test_resolved_and_dismissed_alerts_do_not_stay_recommended(self):
        from briefing import settle_priority_alert
        from priority_inbox import emit_priority_action

        db_path = self._db()
        resolved_id = emit_priority_action(
            kind="mail_notice",
            title="Jira subscription",
            description="Jira subscription",
            payload={"from": "Jira <billing@atlassian.example>", "subject": "Subscription deactivation warning"},
            priority=2,
            source_key="resolve-jira",
            db_path=db_path,
        )
        dismissed_id = emit_priority_action(
            kind="alert",
            title="Pager",
            description="Pager",
            payload={"subject": "Please confirm by December 1."},
            priority=3,
            source_key="dismiss-pager",
            db_path=db_path,
        )
        _insert_run(db_path, "sifter", {"marker": "mail-row", "scan": {"findings": []}})
        runs_before = _count(db_path, "skill_runs")
        rows_before = _count(db_path, "pending_actions")
        first = self._report(db_path)
        self.assertIn("Verify Jira subscription status.", _section(first, "Recommended Actions"))
        self.assertIn("Verify Pager.", _section(first, "Recommended Actions"))
        self.assertEqual(settle_priority_alert(db_path, resolved_id, dismissed=False)["status"], "ok")
        self.assertEqual(settle_priority_alert(db_path, dismissed_id, dismissed=True)["status"], "ok")
        self.assertEqual(_count(db_path, "pending_actions"), rows_before)
        self.assertEqual(_count(db_path, "skill_runs"), runs_before)
        second = self._report(db_path)
        actions = _section(second, "Recommended Actions")
        self.assertNotIn("Verify Jira", actions)
        self.assertNotIn("Verify Pager", actions)
        self.assertNotIn("Jira", _section(second, "Priority Attention"))
        self.assertIn("No action is justified", _section(second, "Executive Focus"))

    def test_a_seen_alert_is_not_recommended_again_without_new_evidence(self):
        from priority_inbox import emit_priority_action

        db_path = self._db()
        emit_priority_action(
            kind="renewal_notice",
            title="Subscription deactivation warning",
            description="Subscription deactivation warning",
            payload={
                "from": "Jira <billing@atlassian.example>",
                "subject": "Subscription deactivation warning",
                "sent_at": "2026-11-15",
            },
            priority=2,
            source_key="seen-jira",
            db_path=db_path,
        )
        first = self._report(db_path)
        self.assertIn("Verify Jira subscription status.", _section(first, "Recommended Actions"))
        second = self._report(db_path)
        self.assertNotIn("Verify Jira", _section(second, "Recommended Actions"))
        self.assertIn("Verify Jira subscription status.", _section(second, "Executive Focus"))
        self.assertNotIn("No action is justified", _section(second, "Executive Focus"))
        self.assertIn("Current status unverified", _section(second, "Priority Attention"))

    def test_briefing_counts_match_the_stored_rows(self):
        from briefing import brief_counts
        from briefing import pending_category
        from desk_work import add_commitment
        from desk_work import complete_commitment
        from open_loops import emit_open_loop
        from priority_inbox import emit_priority_action

        db_path = self._db()
        emit_priority_action(
            kind="mail_notice",
            title="Statement",
            description="Statement",
            payload={"subject": "Monthly statement"},
            priority=2,
            source_key="count-alert",
            db_path=db_path,
        )
        emit_priority_action(
            kind="new_bill",
            title="Power",
            description="Power",
            payload={"vendor": "Power", "amount": "20", "currency": "USD", "due_date": "2026-12-20"},
            priority=3,
            source_key="count-bill",
            db_path=db_path,
        )
        emit_priority_action(
            kind="role_candidate",
            title="Keep this role",
            description="Keep this role",
            payload={"title": "Keep this role"},
            priority=3,
            source_key="count-role",
            db_path=db_path,
        )
        emit_priority_action(
            kind="linkedin_post_draft",
            title="Draft: hiring",
            description="Draft",
            payload={"title": "Draft: hiring"},
            priority=3,
            source_key="count-draft",
            db_path=db_path,
        )
        done = add_commitment(db_path, "Already finished", "2026-11-01")
        complete_commitment(db_path, done["commitment_id"])
        add_commitment(db_path, "Send the note", "2026-11-22")
        emit_open_loop(
            "cto_radar",
            "cto:https://www.youtube.com/watch?v=count",
            "Fractional CTO youtube",
            detail="youtube research",
            db_path=db_path,
        )
        counts = brief_counts(db_path)
        with sqlite3.connect(db_path) as conn:
            rows = conn.execute(
                "SELECT action_type, title, payload_json, priority, status FROM pending_actions WHERE status = 'pending'"
            ).fetchall()
        classified: dict[str, int] = {}
        for kind, title, payload, priority, status in rows:
            self.assertEqual(status, "pending")
            category = pending_category(
                {"action_type": kind, "title": title, "payload_json": payload, "priority": priority}
            )
            classified[category] = classified.get(category, 0) + 1
        self.assertEqual(counts["priority_alerts"], classified.get("alert", 0))
        self.assertEqual(counts["pending_bills"], classified.get("bill", 0))
        self.assertEqual(counts["pending_approvals"], classified.get("approval", 0))
        self.assertEqual(classified.get("draft", 0), 1)
        self.assertEqual(classified.get("financial_information", 0), 1)
        self.assertEqual(counts["priority_alerts"], 0)
        self.assertEqual(counts["pending_bills"], 1)
        self.assertEqual(counts["pending_approvals"], 1)
        self.assertEqual(counts["open_commitments"], 1)
        report = self._report(db_path)
        self.assertIn("Priority alerts: 0.", report)
        self.assertIn("Pending bills: 1.", report)
        self.assertIn("Pending approvals: 1.", report)
        self.assertIn("Outstanding commitments: 1.", report)
        self.assertIn("financial_information", _section(report, "Priority Attention"))
        self.assertIn("Statement", _section(report, "Priority Attention"))
        self.assertNotIn("requiring verification", report)
        self.assertIn("Send the note", _section(report, "Open Commitments"))
        self.assertNotIn("Already finished", _section(report, "Open Commitments"))
        self.assertNotIn("Draft: hiring", report)
        self.assertNotIn("Power", _section(report, "Open Commitments"))
        self.assertNotIn("Statement", _section(report, "Open Commitments"))
        self.assertNotIn("Keep this role", _section(report, "Open Commitments"))
        self.assertNotIn("Send the note", _section(report, "Recommended Actions"))


class EmailClassTests(unittest.TestCase):
    """Fake messages only. Production code does not special-case these names."""

    def _db(self) -> str:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        db_path = str(Path(self._tmpdir.name) / "t.db")
        Manager(db_path=db_path)
        return db_path

    def _report(self, db_path: str) -> str:
        return generate_executive_summary(
            Manager(db_path=db_path),
            _Silent(),
            now=datetime(2026, 11, 22, 8, 0),
        )

    def test_message_classes_do_not_invent_an_action(self):
        from briefing import classify_email
        from briefing import verification_justified

        deactivation = {
            "action_type": "renewal_notice",
            "title": "Subscription deactivation warning",
            "description": "Subscription deactivation warning",
            "payload_json": {"from": "Billing <billing@example.test>", "subject": "Subscription deactivation warning"},
        }
        promo = {
            "action_type": "mail_notice",
            "title": "Credits are waiting",
            "payload_json": {"from": "Shop <deals@example.test>", "subject": "You have promotional credits. Shop the sale."},
        }
        statement = {
            "action_type": "mail_notice",
            "title": "Monthly statement",
            "payload_json": {"from": "Trips <trips@example.test>", "subject": "Your monthly statement"},
        }
        credit = {
            "action_type": "mail_notice",
            "title": "Credit notice",
            "payload_json": {"from": "Audio <audio@example.test>", "subject": "Your credit is available"},
        }
        bank = {
            "action_type": "mail_notice",
            "title": "Statement ready",
            "payload_json": {"from": "Bank <bank@example.test>", "subject": "Your bank statement is available"},
        }
        documents = {
            "action_type": "mail_notice",
            "title": "Documents",
            "payload_json": {"from": "Cover <cover@example.test>", "subject": "Your insurance documents are ready"},
        }
        self.assertEqual(classify_email(deactivation), "action_required")
        self.assertTrue(verification_justified(deactivation))
        self.assertEqual(classify_email(promo), "promotional")
        self.assertEqual(classify_email(statement), "financial_information")
        self.assertIn(classify_email(credit), {"account_notification", "promotional"})
        self.assertEqual(classify_email(bank), "financial_information")
        self.assertEqual(classify_email(documents), "important_document")
        for row in (promo, statement, credit, bank, documents):
            self.assertNotEqual(classify_email(row), "action_required")
            self.assertFalse(verification_justified(row))

    def test_promotional_and_informational_mail_are_not_priority_alerts(self):
        from briefing import brief_counts
        from priority_inbox import emit_priority_action

        db_path = self._db()
        emit_priority_action(
            kind="mail_notice",
            title="Credits are waiting",
            description="Credits are waiting",
            payload={"from": "Shop <deals@example.test>", "subject": "You have promotional credits. Shop the sale."},
            priority=2,
            source_key="promo",
            db_path=db_path,
        )
        emit_priority_action(
            kind="mail_notice",
            title="Monthly statement",
            description="Monthly statement",
            payload={"from": "Trips <trips@example.test>", "subject": "Your monthly statement"},
            priority=2,
            source_key="statement",
            db_path=db_path,
        )
        emit_priority_action(
            kind="mail_notice",
            title="Credit notice",
            description="Credit notice",
            payload={"from": "Audio <audio@example.test>", "subject": "Your credit is available"},
            priority=2,
            source_key="credit",
            db_path=db_path,
        )
        emit_priority_action(
            kind="mail_notice",
            title="Statement ready",
            description="Statement ready",
            payload={"from": "Bank <bank@example.test>", "subject": "Your bank statement is available"},
            priority=3,
            source_key="bank",
            db_path=db_path,
        )
        emit_priority_action(
            kind="mail_notice",
            title="Documents",
            description="Documents",
            payload={"from": "Cover <cover@example.test>", "subject": "Your insurance documents are ready"},
            priority=2,
            source_key="documents",
            db_path=db_path,
        )
        emit_priority_action(
            kind="mail_notice",
            title="Important notice",
            description="Important notice",
            payload={"from": "Desk <desk@example.test>", "subject": "Important notice"},
            priority=3,
            source_key="status-only",
            db_path=db_path,
        )
        emit_priority_action(
            kind="renewal_notice",
            title="Subscription deactivation warning",
            description="Subscription deactivation warning",
            payload={"from": "Billing <billing@example.test>", "subject": "Subscription deactivation warning"},
            priority=2,
            source_key="cancel",
            db_path=db_path,
        )
        emit_priority_action(
            kind="new_bill",
            title="Power",
            description="Power",
            payload={"vendor": "Power", "amount": "42.00", "currency": "USD", "due_date": "2026-12-01"},
            priority=1,
            source_key="power",
            db_path=db_path,
        )
        before = _count(db_path, "pending_actions")
        report = self._report(db_path)
        self.assertEqual(_count(db_path, "pending_actions"), before)
        counts = brief_counts(db_path)
        self.assertEqual(counts["priority_alerts"], 1)
        self.assertEqual(counts["pending_bills"], 1)
        attention = _section(report, "Priority Attention")
        self.assertIn("Class promotional", attention)
        self.assertIn("Class financial_information", attention)
        self.assertIn("Class important_document", attention)
        self.assertIn("Your bank statement is available", attention)
        self.assertIn("Your insurance documents are ready", attention)
        self.assertIn("Subscription deactivation warning", attention)
        self.assertIn("Action: verify subscription status.", attention)
        self.assertIn("Why: the stored message is a subscription deactivation warning.", attention)
        self.assertIn("Status: unverified.", attention)
        self.assertIn("Power: $42.00 due December 1.", attention)
        for line in attention.splitlines():
            lowered = line.lower()
            if "shop the sale" in lowered or "monthly statement" in lowered or "insurance documents" in lowered:
                self.assertNotIn("requiring verification", lowered)
                self.assertNotIn("Action:", line)
            if "bank statement" in lowered:
                self.assertIn("Class financial_information", line)
                self.assertNotIn("Action:", line)
        actions = _section(report, "Recommended Actions")
        self.assertIn("Verify Billing subscription status.", actions)
        self.assertIn("Review Power bill before December 1.", actions)
        self.assertNotIn("Shop the sale", actions)
        self.assertNotIn("monthly statement", actions.lower())
        self.assertNotIn("insurance documents", actions.lower())
        self.assertNotIn("Important notice", actions)
        self.assertNotIn("Verify Desk", actions)
        focus = _section(report, "Executive Focus")
        self.assertIn("Most important:", focus)
        self.assertIn("Upcoming financial obligations:", focus)
        self.assertEqual(focus.lower().count("verify billing"), 1)
        self.assertNotIn("Shop the sale", focus)

    def test_pending_approvals_are_listed_and_left_untouched(self):
        from briefing import brief_counts
        from priority_inbox import emit_priority_action

        db_path = self._db()
        old = emit_priority_action(
            kind="role_candidate",
            title="Old role",
            description="Old role",
            payload={"title": "Old role"},
            priority=1,
            source_key="old-role",
            db_path=db_path,
        )
        emit_priority_action(
            kind="skill_request",
            title="New skill",
            description="New skill",
            payload={"title": "New skill"},
            priority=1,
            source_key="skill",
            db_path=db_path,
        )
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                "UPDATE pending_actions SET created_at = ? WHERE action_id = ?",
                ("2026-10-01T12:00:00+00:00", old),
            )
            before = [
                (row[0], row[1])
                for row in conn.execute("SELECT action_id, status FROM pending_actions ORDER BY action_id")
            ]
        report = self._report(db_path)
        with sqlite3.connect(db_path) as conn:
            after = [
                (row[0], row[1])
                for row in conn.execute("SELECT action_id, status FROM pending_actions ORDER BY action_id")
            ]
        self.assertEqual(after, before)
        self.assertEqual(brief_counts(db_path)["pending_approvals"], 2)
        focus = _section(report, "Executive Focus")
        self.assertIn("Pending approvals: 2.", focus)
        self.assertIn("role_candidate 1", focus)
        self.assertIn("skill_request 1", focus)
        self.assertIn("Oldest pending October 1.", focus)
        self.assertIn("Awaiting the owner: ", focus)
        self.assertIn("Old role", focus)
        self.assertIn("New skill", focus)
        self.assertIn("Stale and may need review: 1.", focus)
        self.assertNotIn("Old role", _section(report, "Recommended Actions"))

    def test_dismissed_items_do_not_return_as_recommendations(self):
        from briefing import settle_priority_alert
        from priority_inbox import emit_priority_action

        db_path = self._db()
        notice = emit_priority_action(
            kind="renewal_notice",
            title="Subscription deactivation warning",
            description="Subscription deactivation warning",
            payload={"from": "Billing <billing@example.test>", "subject": "Subscription deactivation warning"},
            priority=2,
            source_key="gone",
            db_path=db_path,
        )
        first = self._report(db_path)
        self.assertIn("Verify Billing subscription status.", _section(first, "Recommended Actions"))
        self.assertEqual(settle_priority_alert(db_path, notice, dismissed=True)["status"], "ok")
        self.assertEqual(_count(db_path, "pending_actions"), 1)
        second = self._report(db_path)
        self.assertNotIn("Verify Billing", _section(second, "Recommended Actions"))
        self.assertNotIn("Subscription deactivation warning", _section(second, "Priority Attention"))
        self.assertIn("No recommendation is justified", second)


class AgreedRuleTests(unittest.TestCase):
    """The two checks, in order, on fake rows. No network."""

    def _db(self) -> str:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        db_path = str(Path(self._tmpdir.name) / "t.db")
        Manager(db_path=db_path)
        return db_path

    def _report(self, db_path: str) -> str:
        return generate_executive_summary(
            Manager(db_path=db_path),
            _Silent(),
            now=datetime(2026, 11, 22, 8, 0),
        )

    def test_harm_is_an_alert_and_a_discount_deadline_is_not(self):
        from briefing import brief_counts
        from briefing import classify_email
        from priority_inbox import emit_priority_action

        warning = {
            "action_type": "renewal_notice",
            "title": "Subscription notice",
            "payload_json": {
                "from": "Billing <billing@example.test>",
                "subject": "Your subscription will be deactivated",
                "snippet": "Your subscription will be deactivated",
            },
        }
        discount = {
            "action_type": "mail_notice",
            "title": "Offer",
            "payload_json": {
                "from": "Shop <deals@example.test>",
                "subject": "Reply by Friday or this discount expires.",
                "snippet": "Reply by Friday or this discount expires.",
            },
        }
        statement = {
            "action_type": "mail_notice",
            "title": "Statement ready",
            "payload_json": {"subject": "Your statement is available", "snippet": "Your statement is available"},
        }
        credit = {
            "action_type": "mail_notice",
            "title": "Credit notice",
            "payload_json": {"subject": "Your credit is available", "snippet": "Your credit is available"},
        }
        documents = {
            "action_type": "mail_notice",
            "title": "Documents",
            "payload_json": {
                "subject": "Your insurance documents are ready",
                "snippet": "Your insurance documents are ready",
            },
        }
        pay = {
            "action_type": "mail_notice",
            "title": "Payment",
            "payload_json": {
                "from": "Accounts <accounts@example.test>",
                "subject": "Please pay by December 10.",
                "snippet": "Please pay by December 10.",
            },
        }
        self.assertEqual(classify_email(warning), "action_required")
        self.assertEqual(classify_email(discount), "promotional")
        self.assertEqual(classify_email(statement), "financial_information")
        self.assertEqual(classify_email(credit), "account_notification")
        self.assertEqual(classify_email(documents), "important_document")
        self.assertEqual(classify_email(pay), "action_required")

        db_path = self._db()
        emit_priority_action(
            kind="renewal_notice",
            title="Subscription notice",
            description="Subscription notice",
            payload=warning["payload_json"],
            priority=2,
            source_key="warn",
            db_path=db_path,
        )
        emit_priority_action(
            kind="mail_notice",
            title="Offer",
            description="Offer",
            payload=discount["payload_json"],
            priority=3,
            source_key="deal",
            db_path=db_path,
        )
        report = self._report(db_path)
        self.assertEqual(brief_counts(db_path)["priority_alerts"], 1)
        attention = _section(report, "Priority Attention")
        actions = _section(report, "Recommended Actions")
        self.assertIn("Your subscription will be deactivated", attention)
        self.assertIn("Current status unverified", attention)
        self.assertIn("Verify Billing subscription status.", actions)
        self.assertNotIn("has been deactivated", report.lower())
        self.assertNotIn("already deactivated", report.lower())
        self.assertNotIn("was deactivated", report.lower())
        self.assertNotIn("is deactivated", report.lower())
        self.assertIn("Class promotional", attention)
        self.assertNotIn("Reply by Friday", actions)
        self.assertNotIn("discount", actions.lower())
        focus = _section(report, "Executive Focus")
        self.assertIn("Verify Billing subscription status.", focus)
        self.assertNotIn("No action is justified", focus)
        self.assertEqual(focus.lower().count("verify billing subscription status"), 1)

    def test_please_pay_by_a_date_is_an_action_and_a_future_bill_is_upcoming(self):
        from briefing import brief_counts
        from priority_inbox import emit_priority_action

        db_path = self._db()
        emit_priority_action(
            kind="mail_notice",
            title="Payment",
            description="Payment",
            payload={
                "from": "Accounts <accounts@example.test>",
                "subject": "Please pay by December 10.",
                "snippet": "Please pay by December 10.",
            },
            priority=2,
            source_key="pay-by",
            db_path=db_path,
        )
        emit_priority_action(
            kind="new_bill",
            title="North Grid",
            description="North Grid",
            payload={"vendor": "North Grid", "amount": "18.00", "currency": "USD", "due_date": "2026-12-10"},
            priority=1,
            source_key="grid-bill",
            db_path=db_path,
        )
        report = self._report(db_path)
        self.assertEqual(brief_counts(db_path)["priority_alerts"], 1)
        self.assertEqual(brief_counts(db_path)["pending_bills"], 1)
        focus = _section(report, "Executive Focus")
        actions = _section(report, "Recommended Actions")
        self.assertIn("Pay Accounts by december 10.", actions)
        self.assertIn("Reason: the message asks for payment by that date.", actions)
        self.assertIn("Review the upcoming North Grid bill.", focus)
        self.assertIn("Review North Grid bill before December 10.", actions)
        self.assertIn("Payment status unverified.", _section(report, "Priority Attention"))
        self.assertNotIn("overdue", report.lower())
        self.assertNotIn("unpaid", report.lower())
        self.assertNotIn("No action is justified", focus)

    def test_a_known_biller_does_not_turn_a_statement_into_an_action(self):
        from billers import add_biller
        from briefing import brief_counts
        from briefing import classify_email
        from priority_inbox import emit_priority_action

        db_path = self._db()
        self.assertEqual(add_biller(db_path, "northgrid.example", "North Grid", "bill")["status"], "ok")
        payload = {
            "from": "North Grid <statements@northgrid.example>",
            "subject": "Your statement is available",
            "snippet": "Your statement is available",
            "amount": "18.00",
            "currency": "USD",
            "due_date": "2026-12-10",
        }
        row = {
            "action_type": "mail_notice",
            "title": "Statement ready",
            "payload_json": payload,
        }
        self.assertEqual(classify_email(row), "financial_information")
        emit_priority_action(
            kind="mail_notice",
            title="Statement ready",
            description="Statement ready",
            payload=payload,
            priority=3,
            source_key="biller-statement",
            db_path=db_path,
        )
        before = _count(db_path, "pending_actions")
        report = self._report(db_path)
        self.assertEqual(_count(db_path, "pending_actions"), before)
        self.assertEqual(brief_counts(db_path)["priority_alerts"], 0)
        self.assertEqual(brief_counts(db_path)["pending_bills"], 0)
        self.assertIn("Class financial_information", _section(report, "Priority Attention"))
        self.assertNotIn("Verify", _section(report, "Recommended Actions"))
        with sqlite3.connect(db_path) as conn:
            status = conn.execute(
                "SELECT status FROM pending_actions WHERE source_key = ?",
                ("biller-statement",),
            ).fetchone()[0]
        self.assertEqual(status, "pending")

    def test_research_rank_keeps_a_generic_job_as_research(self):
        from briefing import rank_research_items

        generic = {
            "title": "Generic software job",
            "snippet": (
                "Full-time software engineer job posting for a large company. "
                "Apply now. This is a generic job with no advisory scope."
            ),
            "classification": "research",
            "url": "https://jobs.example/generic-role",
        }
        advisory = {
            "title": "Fractional CTO advisory",
            "snippet": "Seed to series B software company, about 20 people, needs fractional CTO advisory.",
            "classification": "research",
            "url": "https://example.test/advisory",
        }
        kept = {
            "title": "Kept engagement",
            "snippet": "Fractional CTO advisory for a seed company that already needs a CTO.",
            "classification": "engagement",
            "url": "https://example.test/kept",
        }
        ranked = rank_research_items([generic, advisory, kept])
        self.assertEqual(generic["classification"], "research")
        self.assertEqual([item["classification"] for item in ranked], ["research", "engagement", "research"])
        self.assertEqual(ranked[0]["title"], "Fractional CTO advisory")
        self.assertNotEqual(ranked[-1]["classification"], "engagement")
        self.assertEqual(ranked[-1]["title"], "Generic software job")
