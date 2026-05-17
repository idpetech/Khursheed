import unittest

from skills.lead_scout import LeadScoutSkill


class FakeLeadScoutSkill(LeadScoutSkill):
    def __init__(self):
        super().__init__(api_key="fake")

    def _tavily_search(self, query: str, max_results: int):
        return {
            "results": [
                {
                    "title": "SAP EWM Warehouse Automation",
                    "url": "https://sap-ewm.example",
                    "content": "SAP EWM implementation for warehouse optimization.",
                },
                {
                    "title": "Generative AI for Logistics",
                    "url": "https://genai-logistics.example",
                    "content": "Using generative AI and LLM to automate supply chain.",
                },
                {
                    "title": "General Consulting Firm",
                    "url": "https://general.example",
                    "content": "Management consulting services.",
                },
            ]
        }


class LeadScoutSkillTests(unittest.TestCase):
    def test_returns_scored_leads(self):
        skill = FakeLeadScoutSkill()
        task = {
            "id": "task-1",
            "payload": {"queries": ["warehouse optimization"]},
        }
        result = skill.run(task)

        self.assertEqual(len(result["queries"]), 1)
        leads = result["queries"][0]["leads"]
        self.assertGreater(len(leads), 0)
        # Leads should be sorted by score descending
        scores = [lead["score"] for lead in leads]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_sap_ewm_tagged(self):
        skill = FakeLeadScoutSkill()
        task = {
            "id": "task-2",
            "payload": {"queries": ["SAP EWM roles"]},
        }
        result = skill.run(task)
        leads = result["queries"][0]["leads"]
        sap_leads = [lead for lead in leads if "SAP EWM" in lead["tags"]]
        self.assertGreater(len(sap_leads), 0)

    def test_genai_tagged(self):
        skill = FakeLeadScoutSkill()
        task = {
            "id": "task-3",
            "payload": {"queries": ["AI automation"]},
        }
        result = skill.run(task)
        leads = result["queries"][0]["leads"]
        genai_leads = [lead for lead in leads if "Generative AI" in lead["tags"]]
        self.assertGreater(len(genai_leads), 0)

    def test_general_relevance_fallback(self):
        skill = FakeLeadScoutSkill()
        task = {
            "id": "task-4",
            "payload": {"queries": ["consulting"]},
        }
        result = skill.run(task)
        leads = result["queries"][0]["leads"]
        general_leads = [lead for lead in leads if "General relevance" in lead["tags"]]
        self.assertGreater(len(general_leads), 0)


if __name__ == "__main__":
    unittest.main()
