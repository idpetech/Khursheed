"""The live desk has one model call. A fake client stands in for the network."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from desk_model import ModelSelectionError
from desk_model import call_model
from llm_agent import HeyEmanAgent
from manager import Manager
from skills.blogger import BloggerSkill
from skills.ceo_advisor import CeoAdvisorSkill
from skills.ceo_advisor import _complete as ceo_complete
from skills.icp_finder import _complete as finder_complete
from skills.icp_prospector import IcpProspectorSkill
from skills.sifter import SifterSkill


ASSESSMENT = json.dumps(
    {
        "assessment": "The open commitment is the only commercial item on the desk.",
        "decision": "CONDITIONAL GO",
        "strategic_rationale": "The commitment is already chosen.",
        "commercial_rationale": "A proposal is the path to revenue.",
        "evidence": "The desk lists one open commercial commitment.",
        "unknowns": "Whether the other party will pay.",
        "assumptions": "The commitment is still open.",
        "conditions": "The other party agrees to pay.",
        "resource_commitment": "The time to make the call.",
        "opportunity_cost": "Other outreach waits.",
        "next_action": "Call the prospect this week.",
        "confidence": "Medium, because the desk does not show a price.",
    }
)

DRAFT = json.dumps(
    {
        "title": "Fractional CTOs",
        "body_markdown": "A short post.",
        "hashtags": ["cto"],
        "word_count": 120,
        "bias_tempering": "untempered",
    }
)

COMPANY = {
    "company_name": "Northwind",
    "industry": "saas",
    "employee_count": 30,
    "funding_stage": "seed",
    "has_cto": "no",
    "acquired": "no",
    "is_hiring_ai": "unknown",
}


def _quiet_env(**overrides: str):
    values = {
        "OPENAI_API_KEY": "",
        "ANTHROPIC_API_KEY": "",
        "KHURSHEED_MODEL": "",
    }
    values.update(overrides)
    return patch.dict(os.environ, values, clear=False)


class _Usage:
    def __init__(self, prompt_tokens: int, completion_tokens: int) -> None:
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens


class _Function:
    def __init__(self, name: str, arguments: str) -> None:
        self.name = name
        self.arguments = arguments


class _Message:
    def __init__(self, content: str, function_call: _Function | None = None) -> None:
        self.content = content
        self.function_call = function_call


class _Response:
    def __init__(self, content: str, model: str | None = None, usage: _Usage | None = None, function_call=None) -> None:
        choice = type("Choice", (), {})()
        choice.message = _Message(content, function_call)
        self.choices = [choice]
        self.model = model
        self.usage = usage


class _Completions:
    def __init__(
        self,
        contents: list[str],
        model: str | None = None,
        usage: _Usage | None = None,
        function_call=None,
    ) -> None:
        self.calls: list[dict] = []
        self._contents = list(contents)
        self._model = model
        self._usage = usage
        self._function_call = function_call

    def create(self, **kwargs):
        self.calls.append(kwargs)
        content = self._contents.pop(0) if self._contents else ""
        return _Response(content, self._model, self._usage, self._function_call)


class _OpenAI:
    def __init__(
        self,
        contents: list[str],
        model: str | None = None,
        usage: _Usage | None = None,
        function_call=None,
    ) -> None:
        chat = type("Chat", (), {})()
        chat.completions = _Completions(contents, model, usage, function_call)
        self.chat = chat

    @property
    def calls(self) -> list[dict]:
        return self.chat.completions.calls


class _Messages:
    def __init__(self, response) -> None:
        self.calls: list[dict] = []
        self._response = response

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self._response


class _Claude:
    def __init__(self, response) -> None:
        self.messages = _Messages(response)


class _Block:
    def __init__(self, **kwargs) -> None:
        self.__dict__.update(kwargs)


class _AnthropicUsage:
    def __init__(self) -> None:
        self.input_tokens = 3
        self.output_tokens = 1


class _AnthropicObject:
    def __init__(self) -> None:
        self.model = "claude-3-5-haiku-latest"
        self.usage = _AnthropicUsage()
        self.content = [_Block(type="text", text="from-object")]


class DeskModelTests(unittest.TestCase):
    def test_the_default_is_gpt_4o_mini_and_returns_provider_usage(self):
        fake = _OpenAI(
            ["Noted."],
            model="gpt-4o-mini-2024-07-18",
            usage=_Usage(11, 5),
        )
        with _quiet_env():
            with patch("desk_model._anthropic_client", side_effect=AssertionError("claude")):
                reply = call_model([{"role": "user", "content": "Hi"}], client=fake)
        self.assertEqual(reply.text, "Noted.")
        self.assertEqual(reply.prompt_tokens, 11)
        self.assertEqual(reply.completion_tokens, 5)
        self.assertEqual(reply.model, "gpt-4o-mini-2024-07-18")
        self.assertEqual(fake.calls[0]["model"], "gpt-4o-mini")
        self.assertEqual(set(fake.calls[0]), {"model", "messages"})

    def test_unset_parameters_stay_off_the_openai_request(self):
        fake = _OpenAI(["ok"])
        with _quiet_env(OPENAI_API_KEY="test-openai"):
            reply = call_model(
                [{"role": "user", "content": "Hi"}],
                functions=[{"name": "run_skill", "description": "Run", "parameters": {"type": "object"}}],
                function_call="auto",
                client=fake,
            )
        self.assertEqual(reply.function_call, None)
        self.assertEqual(fake.calls[0]["function_call"], "auto")
        self.assertEqual(fake.calls[0]["functions"][0]["name"], "run_skill")
        self.assertNotIn("temperature", fake.calls[0])
        self.assertNotIn("response_format", fake.calls[0])
        self.assertNotIn("max_tokens", fake.calls[0])

    def test_openai_returns_a_function_call(self):
        fake = _OpenAI(
            [""],
            function_call=_Function("run_skill", json.dumps({"skill_name": "sifter"})),
        )
        with _quiet_env():
            reply = call_model([{"role": "user", "content": "Check mail"}], client=fake)
        self.assertEqual(reply.text, "")
        self.assertEqual(reply.function_call.name, "run_skill")
        self.assertIn("sifter", reply.function_call.arguments)
        self.assertIsNone(reply.prompt_tokens)

    def test_a_blank_model_name_stays_on_the_default(self):
        fake = _OpenAI(["ok"])
        with _quiet_env(KHURSHEED_MODEL="   "):
            call_model([{"role": "user", "content": "Hi"}], model="  gpt-4o-mini  ", client=fake)
        self.assertEqual(fake.calls[0]["model"], "gpt-4o-mini")

    def test_another_model_does_not_call_the_network(self):
        client_calls = []

        class _Client:
            def __getattr__(self, name):
                client_calls.append(name)
                raise AssertionError(name)

        with _quiet_env(OPENAI_API_KEY="test-openai", ANTHROPIC_API_KEY="test-anthropic"):
            with patch("desk_model._openai_client", side_effect=AssertionError("openai")):
                with patch("desk_model._anthropic_client", side_effect=AssertionError("claude")):
                    with patch("httpx.post", side_effect=AssertionError("network")):
                        with self.assertRaises(ModelSelectionError) as caught:
                            call_model(
                                [{"role": "user", "content": "Hi"}],
                                model="gpt-4o",
                                client=_Client(),
                            )
        self.assertIn("gpt-4o", str(caught.exception))
        self.assertIn("Nothing was sent", str(caught.exception))
        self.assertEqual(client_calls, [])

    def test_a_prefixed_openai_name_is_refused(self):
        with _quiet_env():
            with self.assertRaises(ModelSelectionError) as caught:
                call_model([{"role": "user", "content": "Hi"}], model="openai/gpt-4o-mini")
        self.assertIn("Nothing was sent", str(caught.exception))

    def test_claude_without_a_key_does_not_call(self):
        fake = _Claude({"content": [{"type": "text", "text": "no"}]})
        with _quiet_env(KHURSHEED_MODEL="claude-sonnet-4-5", ANTHROPIC_API_KEY="   "):
            with patch("desk_model._openai_client", side_effect=AssertionError("openai")):
                with patch("httpx.post", side_effect=AssertionError("network")):
                    with self.assertRaises(ModelSelectionError) as caught:
                        call_model([{"role": "user", "content": "Hi"}], client=fake)
        self.assertIn("ANTHROPIC_API_KEY", str(caught.exception))
        self.assertIn("Nothing was sent", str(caught.exception))
        self.assertEqual(fake.messages.calls, [])

    def test_claude_is_used_only_when_the_key_and_the_name_are_set(self):
        fake = _Claude(
            {
                "model": "claude-sonnet-4-5",
                "content": [{"type": "text", "text": "kept"}],
                "usage": {"input_tokens": 12, "output_tokens": 4},
            }
        )
        with _quiet_env(KHURSHEED_MODEL="anthropic/claude-sonnet-4-5", ANTHROPIC_API_KEY="test-anthropic"):
            with patch("desk_model._openai_client", side_effect=AssertionError("openai")):
                with patch("httpx.post", side_effect=AssertionError("network")):
                    reply = call_model(
                        [{"role": "user", "content": "Rank this"}],
                        temperature=0.2,
                        response_format={"type": "json_object"},
                        client=fake,
                    )
        self.assertEqual(reply.text, "kept")
        self.assertEqual(reply.prompt_tokens, 12)
        self.assertEqual(reply.completion_tokens, 4)
        self.assertEqual(reply.model, "claude-sonnet-4-5")
        payload = fake.messages.calls[0]
        self.assertEqual(payload["model"], "anthropic/claude-sonnet-4-5")
        self.assertEqual(payload["temperature"], 0.2)
        self.assertEqual(payload["max_tokens"], 4096)
        self.assertNotIn("response_format", payload)
        self.assertIn("JSON object", payload["system"])
        self.assertNotIn("test-anthropic", json.dumps(payload))

    def test_an_explicit_default_ignores_a_claude_setting(self):
        fake = _OpenAI(["ok"])
        with _quiet_env(KHURSHEED_MODEL="claude-sonnet-4-5", ANTHROPIC_API_KEY="test-anthropic"):
            with patch("desk_model._anthropic_client", side_effect=AssertionError("claude")):
                reply = call_model(
                    [{"role": "user", "content": "Hi"}],
                    model="gpt-4o-mini",
                    client=fake,
                )
        self.assertEqual(reply.text, "ok")
        self.assertEqual(fake.calls[0]["model"], "gpt-4o-mini")

    def test_claude_object_usage_and_tool_call(self):
        response = _AnthropicObject()
        response.content.append(_Block(type="tool_use", name="run_skill", input={"skill_name": "sifter"}))
        fake = _Claude(response)
        messages = [
            {"role": "system", "content": "You are Hey Enaam."},
            {"role": "user", "content": "Check mail"},
            {
                "role": "assistant",
                "content": None,
                "function_call": {"name": "list_skills", "arguments": "{}"},
            },
            {"role": "function", "name": "list_skills", "content": '{"skills": ["sifter"]}'},
        ]
        functions = [{"name": "run_skill", "description": "Run", "parameters": {"type": "object", "properties": {}}}]
        with _quiet_env(ANTHROPIC_API_KEY="test-anthropic"):
            reply = call_model(
                messages,
                model="Claude-Sonnet-4-5",
                functions=functions,
                function_call="auto",
                max_tokens=800,
                client=fake,
            )
        self.assertEqual(reply.text, "from-object")
        self.assertEqual(reply.prompt_tokens, 3)
        self.assertEqual(reply.completion_tokens, 1)
        self.assertEqual(reply.model, "claude-3-5-haiku-latest")
        self.assertEqual(reply.function_call.name, "run_skill")
        self.assertEqual(json.loads(reply.function_call.arguments), {"skill_name": "sifter"})
        payload = fake.messages.calls[0]
        self.assertEqual(payload["max_tokens"], 800)
        self.assertEqual(payload["tool_choice"], {"type": "auto"})
        self.assertEqual(payload["tools"][0]["name"], "run_skill")
        self.assertEqual(payload["system"], "You are Hey Enaam.")
        tool_use = payload["messages"][1]["content"][0]
        self.assertEqual(tool_use["type"], "tool_use")
        self.assertEqual(payload["messages"][2]["content"][0]["tool_use_id"], tool_use["id"])
        self.assertEqual(payload["messages"][2]["content"][0]["type"], "tool_result")

    def test_claude_http_puts_the_key_in_the_header_only(self):
        captured = {}

        class _Http:
            status_code = 200

            def json(self):
                return {
                    "model": "claude-sonnet-4-5",
                    "content": [{"type": "text", "text": "ok"}],
                    "usage": {"input_tokens": 1, "output_tokens": 2},
                }

        def _post(url, headers, json, timeout):
            captured["url"] = url
            captured["headers"] = headers
            captured["json"] = json
            captured["timeout"] = timeout
            return _Http()

        with _quiet_env(ANTHROPIC_API_KEY="test-anthropic"):
            with patch("httpx.post", _post):
                reply = call_model(
                    [{"role": "user", "content": "Hi"}],
                    model="claude-sonnet-4-5",
                )
        self.assertEqual(reply.text, "ok")
        self.assertEqual(reply.prompt_tokens, 1)
        self.assertEqual(reply.completion_tokens, 2)
        self.assertEqual(captured["headers"]["x-api-key"], "test-anthropic")
        self.assertNotIn("test-anthropic", json.dumps(captured["json"]))
        self.assertEqual(captured["json"]["model"], "claude-sonnet-4-5")
        self.assertIn("api.anthropic.com", captured["url"])

    def test_claude_http_failure_does_not_include_the_key(self):
        class _Http:
            status_code = 401
            text = "invalid x-api-key test-anthropic"

            def json(self):
                return {}

        with _quiet_env(ANTHROPIC_API_KEY="test-anthropic"):
            with patch("httpx.post", return_value=_Http()):
                with self.assertRaises(RuntimeError) as caught:
                    call_model([{"role": "user", "content": "Hi"}], model="claude-sonnet-4-5")
        self.assertIn("401", str(caught.exception))
        self.assertNotIn("test-anthropic", str(caught.exception))

        def _post(*_args, **_kwargs):
            import httpx

            raise httpx.ConnectError("down")

        with _quiet_env(ANTHROPIC_API_KEY="test-anthropic"):
            with patch("httpx.post", _post):
                with patch("desk_model._openai_client", side_effect=AssertionError("openai")):
                    with self.assertRaises(RuntimeError) as caught:
                        call_model([{"role": "user", "content": "Hi"}], model="claude-sonnet-4-5")
        self.assertIn("connection", str(caught.exception).lower())
        self.assertNotIn("test-anthropic", str(caught.exception))


class CallSiteTests(unittest.TestCase):
    def test_chat_keeps_the_tool_request_and_refuses_another_model(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "t.db")
            manager = Manager(db_path=db_path)
            fake = _OpenAI(["Noted."])
            agent = HeyEmanAgent(manager)
            agent._client = fake
            with _quiet_env():
                self.assertEqual(agent.respond("second question"), "Noted.")
            self.assertEqual(fake.calls[0]["model"], "gpt-4o-mini")
            self.assertEqual(fake.calls[0]["function_call"], "auto")
            self.assertIn("run_skill", {item["name"] for item in fake.calls[0]["functions"]})
            self.assertNotIn("temperature", fake.calls[0])
            self.assertIn("second question", fake.calls[0]["messages"][-1]["content"])

            refused = HeyEmanAgent(manager, model="gpt-4o")
            refused._client = _OpenAI(["should not be asked"])
            with _quiet_env(OPENAI_API_KEY="test-openai", ANTHROPIC_API_KEY="test-anthropic"):
                with patch("httpx.post", side_effect=AssertionError("network")):
                    text = refused.respond("hi")
            self.assertIn("Nothing was sent", text)
            self.assertIn("gpt-4o", text)
            self.assertEqual(refused._client.calls, [])

    def test_ceo_keeps_json_mode_temperature_and_one_retry(self):
        fake = _OpenAI(["I think this is fine.", ASSESSMENT])
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "t.db")
            Manager(db_path=db_path)
            with _quiet_env(OPENAI_API_KEY="test-openai"):
                with patch("desk_model._openai_client", return_value=fake):
                    result = CeoAdvisorSkill().run(
                        {"db_path": db_path, "payload": {"question": "Review the quarter."}}
                    )
        self.assertEqual(len(fake.calls), 2)
        self.assertEqual(fake.calls[0]["temperature"], 0.2)
        self.assertEqual(fake.calls[0]["response_format"], {"type": "json_object"})
        self.assertEqual(fake.calls[0]["model"], "gpt-4o-mini")
        self.assertNotIn("max_tokens", fake.calls[0])
        self.assertIn("Review the quarter.", fake.calls[0]["messages"][1]["content"])
        self.assertIn("not a valid JSON decision", fake.calls[1]["messages"][1]["content"])
        self.assertEqual(result["decision"], "CONDITIONAL GO")

        with _quiet_env():
            with patch("desk_model._openai_client", side_effect=AssertionError("openai")):
                with patch("desk_model._anthropic_client", side_effect=AssertionError("claude")):
                    missing = CeoAdvisorSkill().run(
                        {"db_path": db_path, "payload": {"question": "Review the quarter."}}
                    )
        self.assertIn("needs the model", missing["error"])
        self.assertIn("OPENAI_API_KEY", missing["error"])

    def test_ceo_complete_returns_stripped_text(self):
        fake = _OpenAI(["  {\"decision\": \"GO\"}  "])
        with _quiet_env(OPENAI_API_KEY="test-openai"):
            with patch("desk_model._openai_client", return_value=fake):
                text = ceo_complete("Review the quarter.", "A commitment is open.")
        self.assertEqual(text, '{"decision": "GO"}')
        self.assertIn("A commitment is open.", fake.calls[0]["messages"][1]["content"])

    def test_finder_keeps_temperature_and_token_limit(self):
        fake = _OpenAI(["[]"])
        with _quiet_env(OPENAI_API_KEY="test-openai"):
            with patch("desk_model._openai_client", return_value=fake):
                text = finder_complete("Pick real companies")
        self.assertEqual(text, "[]")
        self.assertEqual(fake.calls[0]["temperature"], 0)
        self.assertEqual(fake.calls[0]["max_tokens"], 1200)
        self.assertEqual(fake.calls[0]["model"], "gpt-4o-mini")
        self.assertEqual(fake.calls[0]["messages"], [{"role": "user", "content": "Pick real companies"}])
        self.assertNotIn("response_format", fake.calls[0])

    def test_prospector_retries_once_and_keeps_json_mode(self):
        fake = _OpenAI(["", "   "])
        with _quiet_env(OPENAI_API_KEY="test-openai"):
            with patch("desk_model._openai_client", return_value=fake):
                result = IcpProspectorSkill()._rank_companies([COMPANY], 1)
        self.assertEqual(len(fake.calls), 2)
        self.assertEqual(fake.calls[0]["temperature"], 0.1)
        self.assertEqual(fake.calls[0]["max_tokens"], 2000)
        self.assertEqual(fake.calls[0]["response_format"], {"type": "json_object"})
        self.assertEqual(fake.calls[0]["model"], "gpt-4o-mini")
        self.assertIn("FRACTIONAL CTO", fake.calls[0]["messages"][0]["content"])
        self.assertIn("no ranking", result["error"])

    def test_prospector_without_a_key_does_not_call(self):
        with _quiet_env():
            with patch("desk_model._openai_client", side_effect=AssertionError("openai")):
                with patch("desk_model._anthropic_client", side_effect=AssertionError("claude")):
                    result = IcpProspectorSkill()._rank_companies([COMPANY], 1)
        self.assertTrue(result["top_companies"])
        self.assertNotIn("error", result)

    def test_prospector_refuses_another_model_without_calling(self):
        with _quiet_env(OPENAI_API_KEY="test-openai", KHURSHEED_MODEL="gpt-4o"):
            with patch("desk_model._openai_client", side_effect=AssertionError("openai")):
                with patch("httpx.post", side_effect=AssertionError("network")):
                    result = IcpProspectorSkill()._rank_companies([COMPANY], 1)
        self.assertIn("Nothing was sent", result["error"])
        self.assertEqual(result["top_companies"], [])

    def test_sifter_keeps_its_prompt_and_a_refused_model_falls_back(self):
        extraction = json.dumps(
            {
                "kind": "overdue_payment",
                "vendor": "TestService",
                "amount": 89.99,
                "currency": "USD",
                "due_date": None,
                "confidence": "high",
                "action_required": "Pay immediately",
            }
        )
        fake = _OpenAI([extraction])
        skill = SifterSkill(accounts=[])
        with _quiet_env(OPENAI_API_KEY="test-openai"):
            with patch("desk_model._openai_client", return_value=fake):
                parsed = skill._extract_financial_details(
                    "Payment overdue",
                    "billing@testservice.com",
                    "Your payment of $89.99 is past due.",
                    "overdue_payment",
                )
        self.assertEqual(parsed["kind"], "overdue_payment")
        self.assertEqual(fake.calls[0]["temperature"], 0.1)
        self.assertEqual(fake.calls[0]["max_tokens"], 200)
        self.assertEqual(fake.calls[0]["model"], "gpt-4o-mini")
        prompt = fake.calls[0]["messages"][0]["content"]
        self.assertIn("Payment overdue", prompt)
        self.assertIn("kind \"none\"", prompt)
        self.assertNotIn("response_format", fake.calls[0])

        with _quiet_env(OPENAI_API_KEY="test-openai", KHURSHEED_MODEL="gpt-4o"):
            with patch("desk_model._openai_client", side_effect=AssertionError("openai")):
                with patch("httpx.post", side_effect=AssertionError("network")):
                    fallback = skill._extract_financial_details(
                        "Payment overdue",
                        "billing@testservice.com",
                        "Your payment of $89.99 is past due.",
                        "overdue_payment",
                    )
        self.assertEqual(fallback["kind"], "overdue_payment")
        self.assertEqual(fallback["confidence"], "low")

    def test_blogger_keeps_its_prompts(self):
        fake = _OpenAI([DRAFT])
        skill = BloggerSkill()
        with _quiet_env(OPENAI_API_KEY="test-openai"):
            with patch("desk_model._openai_client", return_value=fake):
                draft = skill._generate_content_with_llm(
                    object(),
                    "fractional CTOs",
                    "direct",
                    "short",
                    "No factual context available.",
                    None,
                    None,
                )
        self.assertEqual(draft["title"], "Fractional CTOs")
        self.assertEqual(fake.calls[0]["temperature"], 0.7)
        self.assertEqual(fake.calls[0]["max_tokens"], 2000)
        self.assertEqual(fake.calls[0]["model"], "gpt-4o-mini")
        self.assertIn("tone: direct", fake.calls[0]["messages"][0]["content"])
        self.assertIn("fractional CTOs", fake.calls[0]["messages"][1]["content"])
        self.assertIn("Return ONLY valid JSON", fake.calls[0]["messages"][0]["content"])

        with _quiet_env(KHURSHEED_MODEL="gpt-4o", OPENAI_API_KEY="test-openai"):
            with patch("desk_model._openai_client", side_effect=AssertionError("openai")):
                with patch("httpx.post", side_effect=AssertionError("network")):
                    refused = skill._generate_content_with_llm(
                        object(),
                        "fractional CTOs",
                        "direct",
                        "short",
                        "No factual context available.",
                        None,
                        None,
                    )
        self.assertIsNone(refused)


if __name__ == "__main__":
    unittest.main()
