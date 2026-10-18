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
            output_text = self._run_tool_loop(messages)
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
            "and 'blogger' for a LinkedIn draft. The blogger payload REQUIRES a "
            "'theme' string; derive it from the user's request and always include it, "
            'e.g. payload {"mode": "draft", "theme": "fractional CTOs"}. '
            "Use mode='publish' only when the user explicitly says publish. "
            'For scout, pass payload {"query": "the search"}.\n'
            "When the user asks what is urgent, call list_priority_actions first. "
            "When the user wants a summary, call executive_summary. "
            "When you report priority alerts, reproduce the tool result's 'formatted' field "
            "verbatim. Do not rewrite titles, reformat amounts or dates, or invent values. "
            "It already includes From, Subject, Mailbox, Sent, and Recorded; if a line says "
            "'not recorded', keep it exactly as 'not recorded'. "
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

    def _run_tool_loop(self, messages: list[dict[str, Any]], max_steps: int = 4) -> str:
        """Drive a bounded multi-step tool-calling conversation.

        The model may call tools several times (e.g. retry a skill after an
        error) before producing a final answer. We cap the number of tool
        steps to stay simple and avoid runaway loops.
        """
        functions = [tool["function"] for tool in self._tool_definitions()]
        tool_used = False
        for _ in range(max_steps):
            response = self._openai().chat.completions.create(
                model=self._model,
                messages=messages,
                functions=functions,
                function_call="auto",
            )
            message = response.choices[0].message
            function_call = message.function_call

            if not function_call:
                default = "Task completed." if tool_used else "No response available."
                return message.content or default

            tool_used = True
            name = function_call.name
            args = json.loads(function_call.arguments or "{}")
            result = self._dispatch_function(name, args)

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

        # Budget exhausted: ask for a final answer without more tool calls.
        follow_up = self._openai().chat.completions.create(
            model=self._model,
            messages=messages,
        )
        return follow_up.choices[0].message.content or "Task completed."

    def _dispatch_function(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        if name == "run_skill":
            skill_name = args.get("skill_name")
            payload = args.get("payload", {})
            return self._run_skill(skill_name, payload)
        if name == "list_skills":
            return {"skills": self._manager.list_skill_names()}
        if name == "executive_summary":
            return {"summary": self._generate_summary()}
        if name == "list_priority_actions":
            return self._list_priority_actions()
        return {"error": f"Unknown function '{name}'."}

    def _run_skill(self, skill_name: str, payload: dict[str, Any]) -> dict[str, Any]:
        if not skill_name:
            return {"error": "skill_name is required"}
        task_id = f"llm-{skill_name}-{datetime.now(UTC).isoformat()}"
        try:
            return self._manager.run_skill(skill_name, task_id, payload)
        except (KeyError, ValueError, RuntimeError, OSError) as exc:
            return {"error": str(exc)}

    def _generate_summary(self) -> str:
        return generate_executive_summary(self._manager, MarkdownFileNotifier())

    def _list_priority_actions(self) -> dict[str, Any]:
        from executive_summary import _format_priority_alerts

        data = priority_inbox.list_priority_actions(db_path=str(self._db_path))
        actions = data.get("actions", []) if isinstance(data, dict) else []
        # Provide a ready-made, detail-preserving rendering so the model does not
        # drop From/Subject/Mailbox/Sent/Recorded or invent fields.
        data["formatted"] = _format_priority_alerts(actions)
        return data
