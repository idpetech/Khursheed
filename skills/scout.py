import os
from typing import Any, Dict, List

from skills.base import Skill
from skills.tavily_client import tavily_search


class ScoutSkill(Skill):
    name = "scout"

    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = api_key or os.getenv("TAVILY_API_KEY", "")

    def run(self, task: Dict[str, Any]) -> Dict[str, Any]:
        query = task.get("payload", {}).get("query")
        if not query:
            raise ValueError("Scout skill requires payload.query")
        if not self._api_key:
            raise ValueError("TAVILY_API_KEY is required for Scout skill")

        companies = self._find_companies(query, limit=5)
        enriched: List[Dict[str, Any]] = []
        for company in companies:
            pain_point = self._deep_dive(company["name"], query)
            assessment_hook = self._assessment_hook(company["name"], pain_point)
            enriched.append(
                {
                    "name": company["name"],
                    "source_url": company["url"],
                    "pain_point": pain_point,
                    "assessment_hook": assessment_hook,
                }
            )

        return {"query": query, "companies": enriched}

    def _find_companies(self, query: str, limit: int = 5) -> List[Dict[str, str]]:
        data = self._tavily_search(query, max_results=limit)
        results = data.get("results", [])
        companies: List[Dict[str, str]] = []
        for item in results:
            title = item.get("title") or item.get("url") or "Unknown"
            companies.append({"name": title, "url": item.get("url", "")})
        return companies[:limit]

    def _deep_dive(self, company_name: str, query: str) -> str:
        deep_query = f"{company_name} technical pain point {query}"
        data = self._tavily_search(deep_query, max_results=3)
        results = data.get("results", [])
        if not results:
            return "Needs deeper research to confirm technical pain points."
        snippet = results[0].get("content") or results[0].get("title") or ""
        return snippet.strip() or "Needs deeper research to confirm technical pain points."

    def _assessment_hook(self, company_name: str, pain_point: str) -> str:
        return (
            "With 36 years in IT and leadership experience at Johnson & Johnson, "
            f"I have helped teams resolve issues like: {pain_point}. "
            f"If {company_name} is dealing with similar challenges, I can share a concise "
            "assessment of risks, quick wins, and a modernization path tailored to your stack."
        )

    def _tavily_search(self, query: str, max_results: int) -> Dict[str, Any]:
        return tavily_search(query, max_results, api_key=self._api_key)
