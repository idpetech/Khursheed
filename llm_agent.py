from __future__ import annotations

import json
from datetime import UTC
from datetime import datetime
from typing import Any

from openai import APIConnectionError
from openai import OpenAI

import priority_inbox
from chat_memory import load_recent_turns
from chat_memory import record_turn
from executive_summary import generate_executive_summary
from manager import Manager
from notifications import MarkdownFileNotifier
from principal_profile import principal_prompt_block


class HeyEmanAgent:
    def __init__(self, manager: Manager, model: str = "gpt-4o-mini", profile_path: str | None = None) -> None:
        self._manager = manager
        self._client = None
        self._model = model
        self._profile_path = profile_path
        self._db_path = manager._db_path

    def respond(self, query: str, session_id: str = "hey-eman") -> str:
        history = load_recent_turns(session_id, db_path=self._db_path, limit=8)
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": self._system_prompt()},
        ]
        for turn in history:
            messages.append({"role": "user", "content": turn["user_content"]})
            messages.append({"role": "assistant", "content": turn["assistant_content"]})
        messages.append({"role": "user", "content": query})
        try:
            response = self._openai().chat.completions.create(
                model=self._model,
                messages=messages,
                functions=[tool["function"] for tool in self._tool_definitions()],
                function_call="auto",
            )
            output_text = self._handle_function_calls(response, messages)
        except APIConnectionError:
            output_text = (
                "OpenAI connection error. Please check network access and try again. "
                "You can still use local commands like 'check emails' or 'run tasks'."
            )
        record_turn(session_id, query, output_text, db_path=self._db_path)
        return output_text

    def _openai(self) -> OpenAI:
        if self._client is None:
            self._client = OpenAI()
        return self._client

    def _system_prompt(self) -> str:
        skill_names = ", ".join(self._manager.list_skill_names()) or "(none registered)"
        base = (
            "You are Hey Enaam, a concise executive assistant.\n"
            f"Registered skills: {skill_names}.\n"
            "Use run_skill to run one of those skills. "
            "Use 'sifter' for email, 'cto_radar' for fractional CTO opportunities, "
            "'icp_prospector' for target companies, 'lead_scout' for general lead generation, "
            "and 'blogger' with mode='draft' for a LinkedIn draft. "
            "Use mode='publish' only when the user explicitly says publish.\n"
            "When the user asks what is urgent, call list_priority_actions first. "
            "When the user wants a summary, call executive_summary. "
            "When you report a priority alert, keep From, Subject, Mailbox, Sent, and Recorded. "
            "If a line says not recorded, say that it was not recorded. "
            "Always use the appropriate tool and summarize the result clearly."
        )
        return base + principal_prompt_block(self._profile_path)

    def _tool_definitions(self) -> list[dict[str, Any]]:
        skill_names = self._manager.list_skill_names()
        skill_schema: dict[str, Any] = {
            "type": "string",
            "description": "Registered skill name.",
        }
        if skill_names:
            skill_schema["enum"] = skill_names
        return [
            {
                "type": "function",
                "function": {
                    "name": "run_skill",
                    "description": "Run a registered Khursheed skill.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "skill_name": skill_schema,
                            "payload": {"type": "object"},
                        },
                        "required": ["skill_name"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "list_skills",
                    "description": "List available Khursheed skills.",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "executive_summary",
                    "description": "Generate the daily executive summary.",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "list_priority_actions",
                    "description": "List pending priority actions from the priority inbox.",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
        ]

    def _handle_function_calls(self, response, messages: list[dict[str, Any]]) -> str:
        message = response.choices[0].message
        function_call = message.function_call

        if not function_call:
            return message.content or "No response available."

        name = function_call.name
        args = json.loads(function_call.arguments or "{}")

        if name == "run_skill":
            skill_name = args.get("skill_name")
            payload = args.get("payload", {})
            result = self._run_skill(skill_name, payload)
        elif name == "list_skills":
            result = {"skills": self._manager.list_skill_names()}
        elif name == "executive_summary":
            result = {"summary": self._generate_summary()}
        elif name == "list_priority_actions":
            result = self._list_priority_actions()
        else:
            result = {"error": f"Unknown function '{name}'."}

        messages.append({
            "role": "assistant",
            "content": None,
            "function_call": {"name": name, "arguments": function_call.arguments},
        })
        messages.append({
            "role": "function",
            "name": name,
            "content": json.dumps(result),
        })

        follow_up = self._openai().chat.completions.create(
            model=self._model,
            messages=messages,
        )
        return follow_up.choices[0].message.content or "Task completed."

    def _run_skill(self, skill_name: str, payload: dict[str, Any]) -> dict[str, Any]:
        if not skill_name:
            return {"error": "skill_name is required"}
        task_id = f"llm-{skill_name}-{datetime.now(UTC).isoformat()}"
        return self._manager.run_skill(skill_name, task_id, payload)

    def _generate_summary(self) -> str:
        return generate_executive_summary(self._manager, MarkdownFileNotifier())

    def _list_priority_actions(self) -> dict[str, Any]:
        return priority_inbox.list_priority_actions(db_path=str(self._db_path))
