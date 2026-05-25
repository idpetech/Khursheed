from __future__ import annotations

from typing import Any

import requests


class EnaamMCPClient:
    def __init__(self, base_url: str, timeout: int = 30) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    def health(self) -> dict[str, Any]:
        response = requests.get(f"{self._base_url}/health", timeout=self._timeout)
        response.raise_for_status()
        return response.json()

    def capabilities(self) -> dict[str, Any]:
        response = requests.get(f"{self._base_url}/capabilities", timeout=self._timeout)
        response.raise_for_status()
        return response.json()

    def request(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        response_type: str = "json",
        request_id: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "method": method,
            "params": params or {},
            "response_type": response_type,
        }
        if request_id:
            payload["id"] = request_id
        response = requests.post(self._base_url, json=payload, timeout=self._timeout)
        response.raise_for_status()
        return response.json()

    def run_skill(self, skill_name: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.request(
            method="run_skill",
            params={"skill_name": skill_name, "input": payload or {}},
            response_type="json",
        )

    def run_bridge(self, function_name: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.request(
            method="run_bridge",
            params={"function_name": function_name, "params": params or {}},
            response_type="json",
        )

    def chat_query(self, query: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.request(
            method="chat_query",
            params={"query": query, "context": context or {}},
            response_type="chat",
        )
