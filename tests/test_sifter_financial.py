"""
Unit tests for SifterSkill financial detection functionality.
Tests the three financial email types and priority escalation.
"""

import unittest
from unittest.mock import patch, MagicMock
import os

from skills.sifter import SifterSkill


class TestSifterFinancialDetection(unittest.TestCase):
    """Test suite for financial email detection in SifterSkill"""

    def setUp(self):
        """Set up test fixtures"""
        self.skill = SifterSkill(accounts=[])  # Empty accounts for unit testing

    def test_keyword_prefilter(self):
        """Test keyword-based prefiltering for all three financial types"""
        test_cases = [
            # new_bill cases
            ("Your invoice is ready", "billing@aws.com", "Invoice body", "new_bill"),
            ("Statement available", "no-reply@stripe.com", "Payment due", "new_bill"),
            
            # overdue_payment cases  
            ("Payment overdue", "billing@service.com", "Past due notice", "overdue_payment"),
            ("URGENT: Final notice", "billing@host.com", "Account suspended", "overdue_payment"),
            
            # trial_ending cases
            ("Trial expires tomorrow", "team@service.com", "Cancel before", "trial_ending"),
            ("Free trial ends soon", "support@app.com", "Auto-renew on", "trial_ending"),
            
            # Non-financial
            ("Newsletter update", "marketing@company.com", "Regular content", None),
            ("Welcome aboard!", "hello@startup.com", "Getting started", None),
            ("Final notice: 30% off ends at midnight", "matt@aihero.dev", "Sale ends tonight", None),
            ("Final notice", "news@example.com", "Read our latest post", None),
        ]
        
        for subject, sender, body, expected in test_cases:
            with self.subTest(subject=subject):
                result = self.skill._financial_keyword_prefilter(subject, sender, body)
                self.assertEqual(result, expected, 
                    f"Failed for '{subject}': got {result}, expected {expected}")

    def test_fallback_extraction(self):
        """Test keyword-only extraction when OpenAI is unavailable"""
        # Test new_bill extraction
        result = self.skill._fallback_extraction(
            "Invoice from Company: $125.50 due 2024-12-31",
            "billing@company.com", 
            "Your monthly invoice",
            "new_bill"
        )
        
        self.assertEqual(result["kind"], "new_bill")
        self.assertEqual(result["vendor"], "Company")
        self.assertEqual(result["amount"], 125.5)
        self.assertEqual(result["currency"], "USD")
        self.assertEqual(result["due_date"], "2024-12-31")
        self.assertEqual(result["confidence"], "low")

        promo = self.skill._fallback_extraction(
            "Final notice: 30% off ends at midnight",
            "matt@aihero.dev",
            "Sale ends tonight",
            "overdue_payment",
        )
        self.assertIsNone(promo["amount"])

    def test_priority_calculation(self):
        """Test priority and expiry calculation logic"""
        # Test overdue_payment (always priority 3, no expiry)
        priority, expires = self.skill._calculate_priority_and_expiry({
            "kind": "overdue_payment"
        })
        self.assertEqual(priority, 3)
        self.assertIsNone(expires)
        
        # Test new_bill with future date (priority 1)
        priority, expires = self.skill._calculate_priority_and_expiry({
            "kind": "new_bill",
            "due_date": "2027-12-31"  # Far future
        })
        self.assertEqual(priority, 1)
        self.assertIsNotNone(expires)
        
        # Test new_bill without date (default priority 1)
        priority, expires = self.skill._calculate_priority_and_expiry({
            "kind": "new_bill"
        })
        self.assertEqual(priority, 1)
        self.assertIsNone(expires)

    @patch('priority_inbox.emit_priority_action')
    def test_create_priority_action(self, mock_emit):
        """Test priority action creation with correct parameters"""
        mock_emit.return_value = "test-action-id-123"
        
        extraction = {
            "kind": "new_bill",
            "vendor": "TestCorp",
            "amount": 100.0,
            "currency": "USD", 
            "due_date": "2024-12-31",
            "confidence": "high"
        }
        
        action_id = self.skill._create_priority_action(
            extraction, 
            "Test invoice subject",
            "billing@testcorp.com",
            "MSG123", 
            "test_account",
            priority=2,
            expires_at="2024-12-31T23:59:59",
            sent_at="Thu, 28 May 2026 12:00:00 +0000",
        )
        
        self.assertEqual(action_id, "test-action-id-123")
        
        # Verify emit_priority_action was called with correct parameters
        mock_emit.assert_called_once()
        args, kwargs = mock_emit.call_args
        
        self.assertEqual(kwargs["kind"], "new_bill")
        self.assertIn("TestCorp", kwargs["title"])
        self.assertEqual(kwargs["priority"], 2)
        self.assertEqual(kwargs["expires_at"], "2024-12-31T23:59:59")
        self.assertIn("vendor", kwargs["payload"])
        self.assertEqual(kwargs["payload"]["from"], "billing@testcorp.com")
        self.assertEqual(kwargs["payload"]["sent_at"], "Thu, 28 May 2026 12:00:00 +0000")

    @patch('openai.OpenAI')
    @patch('priority_inbox.emit_priority_action')
    def test_detect_financial_urgency_integration(self, mock_emit, mock_openai_class):
        """Test complete financial detection integration with mocked OpenAI"""
        # Setup mocks
        mock_emit.return_value = "test-action-id-456"
        
        mock_client = MagicMock()
        mock_openai_class.return_value = mock_client
        
        # Mock OpenAI response
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = '''{
            "kind": "overdue_payment",
            "vendor": "TestService", 
            "amount": 89.99,
            "currency": "USD",
            "due_date": null,
            "confidence": "high",
            "action_required": "Pay immediately"
        }'''
        mock_client.chat.completions.create.return_value = mock_response
        
        # Set environment variable for OpenAI
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'test-key'}):
            result = self.skill._detect_financial_urgency(
                "URGENT: Payment overdue - final notice",
                "billing@testservice.com",
                "Your payment of $89.99 is past due. Please pay immediately.",
                "MSG456",
                "test_account"
            )
        
        self.assertIsNotNone(result)
        self.assertEqual(result["kind"], "overdue_payment")
        self.assertEqual(result["priority"], 3)  # Overdue should be priority 3
        self.assertEqual(result["action_id"], "test-action-id-456")
        
        # Verify OpenAI was called
        mock_client.chat.completions.create.assert_called_once()

    def test_detect_financial_urgency_no_match(self):
        """Test that non-financial emails don't trigger detection"""
        result = self.skill._detect_financial_urgency(
            "Welcome to our newsletter!",
            "marketing@company.com", 
            "Here are this week's updates and news.",
            "MSG789",
            "test_account"
        )
        
        self.assertIsNone(result)

    @patch("priority_inbox.emit_priority_action")
    def test_low_confidence_does_not_escalate(self, mock_emit):
        with patch.dict(os.environ, {"OPENAI_API_KEY": ""}, clear=False):
            result = self.skill._detect_financial_urgency(
                "Payment overdue",
                "billing@service.com",
                "Past due notice",
                "MSG-low",
                "yahoo",
            )
        self.assertIsNone(result)
        mock_emit.assert_not_called()

    @patch("priority_inbox.emit_priority_action")
    def test_low_confidence_with_due_date_is_saved(self, mock_emit):
        mock_emit.return_value = "bill-1"
        with patch.dict(os.environ, {"OPENAI_API_KEY": ""}, clear=False):
            result = self.skill._detect_financial_urgency(
                "Your JEA eBill is Here",
                "billing@jea.com",
                "Please pay $1,158.00 by 11/05/2027. Your JEA account.",
                "MSG-jea",
                "yahoo2",
            )
        self.assertIsNotNone(result)
        self.assertEqual(result["priority"], 1)
        mock_emit.assert_called_once()
        self.assertEqual(mock_emit.call_args.kwargs["payload"]["due_date"], "2027-11-05")

    def test_model_json_accepts_fenced_object(self):
        parsed = self.skill._parse_model_json(
            '```json\n{"kind": "new_bill", "due_date": "2026-11-05"}\n```'
        )
        self.assertEqual(parsed["kind"], "new_bill")


if __name__ == '__main__':
    unittest.main()