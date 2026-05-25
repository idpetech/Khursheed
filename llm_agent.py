from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from openai import APIConnectionError, OpenAI

from executive_summary import generate_executive_summary
from manager import Manager
from notifications import MarkdownFileNotifier


class HeyEmanAgent:
    def __init__(self, manager: Manager, model: str = "gpt-4o-mini") -> None:
        self._manager = manager
        self._client = OpenAI()
        self._model = model

    def respond(self, query: str) -> str:
        tools = self._tool_definitions()
        messages = [
            {
                "role": "system",
                "content": (
                    "You are Hey Enaam, a concise executive assistant with access to these capabilities:\n"
                    "- run_skill with 'sifter' to check and process emails\n"
                    "- run_skill with 'lead_scout' for lead generation\n"
                    "- run_skill with 'echo' for testing\n"
                    "- executive_summary to generate daily executive summaries\n"
                    "- list_skills to see available skills\n\n"
                    "When users ask about emails, use run_skill with skill_name='sifter'. "
                    "When users want summaries, use executive_summary. "
                    "Always use the appropriate tool and summarize results clearly."
                ),
            },
            {"role": "user", "content": query},
        ]
        try:
            response = self._client.chat.completions.create(
                model=self._model,
                messages=messages,
                functions=[tool["function"] for tool in tools],
                function_call="auto",
            )
            output_text = self._handle_function_calls(response, messages)
            return output_text
        except APIConnectionError:
            return (
                "OpenAI connection error. Please check network access and try again. "
                "You can still use local commands like 'check emails' or 'run tasks'."
            )

    def _tool_definitions(self) -> List[Dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "run_skill",
                    "description": "Run a specific Khursheed skill. Use 'sifter' for email checking, 'lead_scout' for lead generation, 'echo' for testing.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "skill_name": {
                                "type": "string", 
                                "enum": ["sifter", "lead_scout", "echo", "timestamp"],
                                "description": "The skill to run. Use 'sifter' to check emails."
                            },
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
        ]

    def _handle_function_calls(self, response, messages: List[Dict[str, str]]) -> str:
        message = response.choices[0].message
        function_call = message.function_call
        
        if not function_call:
            return message.content or "No response available."

        # Execute the function
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
        else:
            result = {"error": f"Unknown function '{name}'."}
        
        # Add function call and result to conversation
        messages.append({
            "role": "assistant",
            "content": None,
            "function_call": {"name": name, "arguments": function_call.arguments}
        })
        messages.append({
            "role": "function",
            "name": name,
            "content": json.dumps(result)
        })

        # Get final response
        follow_up = self._client.chat.completions.create(
            model=self._model,
            messages=messages,
        )
        return follow_up.choices[0].message.content or "Task completed."

    def _run_skill(self, skill_name: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        if not skill_name:
            return {"error": "skill_name is required"}
        task_id = f"llm-{skill_name}-{datetime.now(timezone.utc).isoformat()}"
        return self._manager.run_skill(skill_name, task_id, payload)

    def _generate_summary(self) -> str:
        return generate_executive_summary(self._manager, MarkdownFileNotifier())
