from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from openai import APIConnectionError, OpenAI

from executive_summary import generate_executive_summary
from manager import Manager
from notifications import MarkdownFileNotifier

logger = logging.getLogger(__name__)


class HeyEmanAgent:
    def __init__(
        self,
        manager: Manager,
        model: str = "gpt-4o-mini",
        api_key: str | None = None,
    ) -> None:
        self._manager = manager
        self._client = OpenAI(api_key=api_key)
        self._model = model

    def respond(self, query: str) -> str:
        tools = self._tool_definitions()
        messages = [
            {
                "role": "system",
                "content": (
                    "You are Hey Eman, a concise executive assistant for Khursheed. "
                    "Use tools to perform tasks when asked, then summarize results clearly. "
                    "Available skills (use exact names only):\n"
                    "  - sifter: checks email inbox (Yahoo/Gmail), categorizes messages, extracts expenses\n"
                    "  - lead_scout: searches the web for business leads (Fractional CTO, warehouse consulting)\n"
                    "  - timestamp: records the current UTC timestamp\n"
                    "  - echo: echoes a message payload\n"
                    "Never invent skill names. Always use run_skill with the exact name from the list above."
                ),
            },
            {"role": "user", "content": query},
        ]
        logger.debug("Preparing OpenAI request (model=%s, query_len=%d)", self._model, len(query))
        try:
            response = self._client.responses.create(
                model=self._model,
                input=messages,
                tools=tools,
            )
            output_text = self._handle_tool_calls(response, messages)
            return output_text
        except APIConnectionError as exc:
            detail = f"{exc} cause={repr(exc.__cause__)}"
            logger.error("APIConnectionError: %s", detail)
            self._log_error("APIConnectionError", detail)
            return self._fallback_message()
        except Exception as exc:  # pylint: disable=broad-except
            logger.error("Unexpected %s: %s", type(exc).__name__, exc)
            self._log_error(type(exc).__name__, str(exc))
            return self._fallback_message(error_name=type(exc).__name__)

    def _fallback_message(self, error_name: str | None = None) -> str:
        suffix = f" ({error_name})" if error_name else ""
        return (
            "OpenAI connection error. Please check network access and try again"
            f"{suffix}. You can still use local commands like 'check emails' "
            "or 'run tasks'."
        )

    def _log_error(self, error_name: str, message: str) -> None:
        log_path = Path(__file__).resolve().parent / "logs" / "llm_errors.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).isoformat()
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(f"[{timestamp}] {error_name}: {message}\n")

    def _tool_definitions(self) -> List[Dict[str, Any]]:
        return [
            {
                "type": "function",
                "name": "run_skill",
                "description": "Run a specific Khursheed skill with payload.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "skill_name": {"type": "string"},
                        "payload": {"type": "object"},
                    },
                    "required": ["skill_name"],
                },
            },
            {
                "type": "function",
                "name": "list_skills",
                "description": "List available Khursheed skills.",
                "parameters": {"type": "object", "properties": {}},
            },
            {
                "type": "function",
                "name": "executive_summary",
                "description": "Generate the daily executive summary.",
                "parameters": {"type": "object", "properties": {}},
            },
        ]

    def _handle_tool_calls(self, response, messages: List[Dict[str, str]]) -> str:
        output_items = response.output or []
        logger.debug("Received %d output items", len(output_items))

        fn_calls = [item for item in output_items if item.type == "function_call"]
        if not fn_calls:
            return response.output_text or "No response available."

        tool_results = []
        for item in fn_calls:
            name = item.name
            args = json.loads(item.arguments or "{}")
            if name == "run_skill":
                skill_name = args.get("skill_name")
                payload = args.get("payload", {})
                result = self._run_skill(skill_name, payload)
            elif name == "list_skills":
                result = {"skills": self._manager.list_skill_names()}
            elif name == "executive_summary":
                result = {"summary": self._generate_summary()}
            else:
                result = {"error": f"Unknown tool '{name}'."}
            tool_results.append(
                {
                    "type": "function_call_output",
                    "call_id": item.call_id,
                    "output": json.dumps(result),
                }
            )

        logger.debug("Submitting %d tool results", len(tool_results))
        follow_up = self._client.responses.create(
            model=self._model,
            previous_response_id=response.id,
            input=tool_results,
            tools=self._tool_definitions(),
        )
        text = follow_up.output_text
        if not text:
            # Flatten any text items from output directly
            text = " ".join(
                item.text for item in (follow_up.output or []) if hasattr(item, "text") and item.text
            )
        return text or "Done. Ask for the executive summary for details."

    def _run_skill(self, skill_name: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        if not skill_name:
            return {"error": "skill_name is required"}
        task_id = f"llm-{skill_name}-{datetime.now(timezone.utc).isoformat()}"
        return self._manager.run_skill(skill_name, task_id, payload)

    def _generate_summary(self) -> str:
        return generate_executive_summary(self._manager, MarkdownFileNotifier())
