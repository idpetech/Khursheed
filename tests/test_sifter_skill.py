import unittest

from skills.sifter import SifterSkill


class SifterSkillTests(unittest.TestCase):
    def setUp(self):
        self.skill = SifterSkill(accounts=[])

    def test_categorize_bills(self):
        category = self.skill._categorize(
            subject="Invoice for services",
            sender="billing@example.com",
            body="Please see attached receipt.",
        )
        self.assertEqual(category, "Urgent/Bill")

    def test_categorize_leads(self):
        category = self.skill._categorize(
            subject="Request for proposal",
            sender="client@example.com",
            body="Can we schedule a demo?",
        )
        self.assertEqual(category, "Potential Lead")

    def test_extract_expense(self):
        expense = self.skill._extract_expense(
            subject="Your OpenAI receipt",
            sender="OpenAI <billing@openai.com>",
            body="Thanks for your payment receipt.",
        )
        self.assertIsNotNone(expense)
        self.assertEqual(expense["vendor"], "OpenAI")


if __name__ == "__main__":
    unittest.main()
