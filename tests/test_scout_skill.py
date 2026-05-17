import unittest

from skills.scout import ScoutSkill


class FakeScoutSkill(ScoutSkill):
    def __init__(self):
        super().__init__(api_key="fake")
        self._calls = []

    def _tavily_search(self, query: str, max_results: int):
        self._calls.append((query, max_results))
        if "technical pain point" in query:
            return {
                "results": [
                    {"title": "Issue", "content": "Latency in data pipelines."}
                ]
            }
        return {
            "results": [
                {"title": "Alpha Systems", "url": "https://alpha.example"},
                {"title": "Beta Labs", "url": "https://beta.example"},
                {"title": "Gamma Tech", "url": "https://gamma.example"},
                {"title": "Delta Works", "url": "https://delta.example"},
                {"title": "Epsilon AI", "url": "https://epsilon.example"},
            ]
        }


class ScoutSkillTests(unittest.TestCase):
    def test_scout_builds_assessment_hooks(self):
        skill = FakeScoutSkill()
        task = {"id": "task-1", "payload": {"query": "tech startups in Florida"}}
        result = skill.run(task)

        self.assertEqual(result["query"], "tech startups in Florida")
        self.assertEqual(len(result["companies"]), 5)
        for company in result["companies"]:
            self.assertIn("pain_point", company)
            self.assertIn("assessment_hook", company)
            self.assertIn("Johnson & Johnson", company["assessment_hook"])


if __name__ == "__main__":
    unittest.main()
