import json
import os
import urllib.request
from typing import Any, Dict


def tavily_search(
    query: str,
    max_results: int,
    api_key: str | None = None,
) -> Dict[str, Any]:
    key = api_key or os.getenv("TAVILY_API_KEY", "")
    if not key:
        raise ValueError("TAVILY_API_KEY is required")
    payload = json.dumps(
        {
            "api_key": key,
            "query": query,
            "search_depth": "advanced",
            "max_results": max_results,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        "https://api.tavily.com/search",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))
