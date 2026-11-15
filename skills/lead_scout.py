import os
from typing import Any, Dict, List

from skills.base import Skill
from skills.tavily_client import tavily_search


class LeadScoutSkill(Skill):
    name = "lead_scout"

    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = api_key or os.getenv("TAVILY_API_KEY", "")

    def run(self, task: Dict[str, Any]) -> Dict[str, Any]:
        if not self._api_key:
            raise ValueError("TAVILY_API_KEY is required for LeadScout skill")

        payload = task.get("payload", {})
        queries = payload.get(
            "queries",
            [
                "Fractional CTO roles in Jacksonville",
                "Warehouse optimization consulting",
            ],
        )
        results: List[Dict[str, Any]] = []
        for query in queries:
            leads = self._search_and_score(query, payload)
            results.append({"query": query, "leads": leads})
        return {"queries": results}

    def _search_and_score(self, query: str, payload: Dict[str, Any] | None = None) -> List[Dict[str, Any]]:
        data = self._tavily_search(query, max_results=8)
        leads: List[Dict[str, Any]] = []
        for item in data.get("results", []):
            title = item.get("title") or "Unknown"
            url = item.get("url") or ""
            snippet = item.get("content") or item.get("title") or ""
            score, tags = self._score_relevance(title, snippet, payload)
            leads.append(
                {
                    "title": title,
                    "url": url,
                    "snippet": snippet.strip(),
                    "score": score,
                    "tags": tags,
                }
            )
        return sorted(leads, key=lambda lead: lead["score"], reverse=True)[:5]

    def _score_relevance(
        self,
        title: str,
        snippet: str,
        payload: Dict[str, Any] | None = None,
    ) -> tuple[int, List[str]]:
        text = f"{title} {snippet}".lower()
        score = 0
        tags: List[str] = []

        sap_keywords = ["sap ewm", "ewm", "sap warehouse", "sap s/4hana"]
        genai_keywords = ["generative ai", "genai", "llm", "openai", "ai automation"]

        if any(keyword in text for keyword in sap_keywords):
            score += 60
            tags.append("SAP EWM")
        if any(keyword in text for keyword in genai_keywords):
            score += 40
            tags.append("Generative AI")
        criteria = payload or {}
        industries = [str(item).strip().lower() for item in criteria.get("industries") or [] if str(item).strip()]
        if any(industry in text for industry in industries):
            score += 50
            tags.append("ICP")
        notes = str(criteria.get("notes") or "")
        phrases = [
            part.strip().lower()
            for part in notes.replace(";", ",").split(",")
            if len(part.strip()) >= 3
        ]
        if any(phrase in text for phrase in phrases):
            score += 20
            tags.append("Notes")
        if "fractional" in text and "cto" in text:
            score += 30
            tags.append("Fractional CTO")
        if not tags:
            score += 10
            tags.append("General relevance")
        return score, tags

    def _tavily_search(self, query: str, max_results: int) -> Dict[str, Any]:
        return tavily_search(query, max_results, api_key=self._api_key)
