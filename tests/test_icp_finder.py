import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from desk_settings import choose_icp_candidate
from desk_settings import list_icp_seed
from manager import Manager
from skills.icp_finder import IcpFinderSkill
from skills.icp_finder import _offer


class FinderTests(unittest.TestCase):
    def test_offer_keeps_named_companies_and_skips_the_list(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "t.db")
            Manager(db_path=db_path)
            from desk_settings import add_icp_company

            add_icp_company(db_path, "Already Listed", industry="saas")
            snippets = [
                {"title": "Northwind raises a seed round", "url": "https://northwind.example", "content": "Northwind"},
                {"title": "Already Listed expands", "url": "https://listed.example", "content": "Already Listed"},
            ]
            extracted = [
                {"company_name": "Northwind", "website": "https://northwind.example", "industry": "saas", "employee_count": 24, "funding_stage": "seed", "why": "Seed-stage SaaS."},
                {"company_name": "Invented Co", "why": "Not in the results."},
                {"company_name": "Already Listed", "industry": "saas"},
            ]
            offered = _offer(extracted, snippets, 5, db_path)
            self.assertEqual([row["company_name"] for row in offered], ["Northwind"])
            self.assertEqual(offered[0]["website"], "https://northwind.example")
            offered_again = _offer(extracted, snippets, 5, db_path)
            self.assertEqual(offered_again, [])

    def test_a_directory_page_is_not_each_companys_website(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "t.db")
            Manager(db_path=db_path)
            page = "https://100xfounder.com/startups/early-stage-startups"
            snippets = [
                {
                    "title": "Early stage startups",
                    "url": page,
                    "content": "Secoda, Capital, and Simplified are on this list.",
                }
            ]
            extracted = [
                {"company_name": "Secoda", "website": page, "industry": "saas", "funding_stage": "seed", "why": "Needs a fractional CTO."},
                {"company_name": "Capital", "website": page, "industry": "fintech", "funding_stage": "seed", "why": "Needs a fractional CTO."},
                {"company_name": "Simplified", "website": page, "industry": "saas", "funding_stage": "seed", "why": "Needs a fractional CTO."},
            ]
            offered = _offer(extracted, snippets, 5, db_path)
            self.assertEqual(
                [row["company_name"] for row in offered],
                ["Secoda", "Capital", "Simplified"],
            )
            self.assertEqual([row["website"] for row in offered], ["", "", ""])

    def test_add_keeps_a_company_and_skip_does_not(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "t.db")
            Manager(db_path=db_path)
            snippets = [{"title": "Brightline", "url": "https://brightline.example", "content": "Brightline"}]
            _offer(
                [{"company_name": "Brightline", "website": "https://brightline.example", "industry": "fintech", "employee_count": 18, "funding_stage": "seed", "why": "No CTO listed."}],
                snippets,
                5,
                db_path,
            )
            import sqlite3

            action_id = sqlite3.connect(db_path).execute(
                "SELECT action_id FROM pending_actions WHERE action_type = 'icp_candidate'"
            ).fetchone()[0]
            self.assertEqual(choose_icp_candidate(db_path, action_id, accept=True)["status"], "ok")
            self.assertIn("Brightline", {row["company_name"] for row in list_icp_seed(db_path)})

            _offer(
                [{"company_name": "Harbor", "industry": "saas", "why": "Series A."}],
                [{"title": "Harbor", "url": "", "content": "Harbor"}],
                5,
                db_path,
            )
            skipped = sqlite3.connect(db_path).execute(
                "SELECT action_id FROM pending_actions WHERE title = 'Harbor'"
            ).fetchone()[0]
            choose_icp_candidate(db_path, skipped, accept=False)
            self.assertNotIn("Harbor", {row["company_name"] for row in list_icp_seed(db_path)})

    def test_run_reports_a_search_failure(self):
        skill = IcpFinderSkill()
        with patch("skills.icp_finder.tavily_search", side_effect=OSError("tunnel failed")):
            result = skill.run({"payload": {"industries": ["saas"], "top_n": 3}, "db_path": ""})
        self.assertEqual(result["candidates"], [])
        self.assertIn("tunnel failed", result["error"])
        self.assertIn("error", json.dumps(result))
