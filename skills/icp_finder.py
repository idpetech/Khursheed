"""Find companies that match the ICP and offer them for a yes or no."""

from __future__ import annotations

import json
import logging
import re
from typing import Any
from urllib.parse import urlparse

from desk_model import call_model
from skills.base import Skill
from skills.tavily_client import tavily_search


logger = logging.getLogger(__name__)


class IcpFinderSkill(Skill):
    name = "icp_finder"

    def run(self, task: dict[str, Any]) -> dict[str, Any]:
        """Search for new companies and leave each one in To review."""
        payload = task.get("payload") or {}
        criteria = _criteria(payload)
        queries = _queries(criteria, payload.get("queries"))
        snippets, errors = self._search(queries)
        if not snippets:
            return {
                "candidates": [],
                "queries": queries,
                "error": errors[0] if errors else "No search results.",
            }
        try:
            extracted = self._extract(snippets, criteria)
        except Exception as exc:
            logger.warning("ICP finder could not read the search results: %s", exc)
            return {"candidates": [], "queries": queries, "error": str(exc)}
        offered = _offer(extracted, snippets, criteria["top_n"], task.get("db_path"))
        return {"candidates": offered, "queries": queries, "considered": len(extracted)}

    def _search(self, queries: list[str]) -> tuple[list[dict[str, str]], list[str]]:
        snippets: list[dict[str, str]] = []
        errors: list[str] = []
        for query in queries:
            try:
                data = tavily_search(query, 5)
            except Exception as exc:
                errors.append(str(exc))
                continue
            for item in data.get("results") or []:
                snippets.append(
                    {
                        "title": str(item.get("title") or ""),
                        "url": str(item.get("url") or ""),
                        "content": str(item.get("content") or ""),
                    }
                )
        return snippets, errors

    def _extract(self, snippets: list[dict[str, str]], criteria: dict[str, Any]) -> list[dict[str, Any]]:
        prompt = _prompt(snippets, criteria)
        text = _complete(prompt)
        parsed = _parse_company_list(text)
        return [row for row in parsed if isinstance(row, dict)]


def _criteria(payload: dict[str, Any]) -> dict[str, Any]:
    industries = payload.get("industries") or ["saas", "fintech", "edtech", "commerce"]
    stages = payload.get("funding_stages") or ["seed", "series-a", "series-b"]
    try:
        top_n = int(payload.get("top_n") or 5)
    except (TypeError, ValueError):
        top_n = 5
    return {
        "industries": [str(item).strip() for item in industries if str(item).strip()],
        "employee_min": payload.get("employee_min", 10),
        "employee_max": payload.get("employee_max", 50),
        "funding_stages": [str(item).strip() for item in stages if str(item).strip()],
        "notes": str(payload.get("notes") or "").strip(),
        "top_n": max(1, min(top_n, 20)),
    }


def _queries(criteria: dict[str, Any], custom: Any) -> list[str]:
    supplied = [str(item).strip() for item in (custom or []) if str(item).strip()]
    if supplied:
        return supplied[:3]
    industries = ", ".join(criteria["industries"]) or "software"
    stages = " OR ".join(criteria["funding_stages"]) or "seed"
    band = f"{criteria['employee_min']}-{criteria['employee_max']} employees"
    base = f"{stages} {industries} startup {band}"
    queries = [f"{base} company", f"{base} no chief technology officer"]
    if criteria["notes"]:
        queries.append(f"{base} {criteria['notes']}")
    return queries[:3]


def _prompt(snippets: list[dict[str, str]], criteria: dict[str, Any]) -> str:
    notes = criteria["notes"] or "No extra notes."
    return (
        "Pick real companies named in the search results that could hire a fractional CTO.\n"
        f"Industries: {', '.join(criteria['industries']) or 'any'}.\n"
        f"Employees: {criteria['employee_min']} to {criteria['employee_max']}.\n"
        f"Funding: {', '.join(criteria['funding_stages']) or 'any'}.\n"
        f"Notes: {notes}\n"
        "Use only companies whose names appear in the results. Do not invent companies.\n"
        "website is that company's own site. If a result is a list of many companies, "
        "leave website empty. Do not copy the list page address onto each company.\n"
        "why is one fact from the result. Do not claim they need a CTO unless the result says so.\n"
        "Return a JSON list, and nothing else. Each item has company_name, website, "
        "industry, employee_count, funding_stage, and why.\n"
        f"Return at most {criteria['top_n']} companies.\n\n"
        f"Search results:\n{json.dumps(snippets)}"
    )


def _complete(prompt: str) -> str:
    reply = call_model(
        [{"role": "user", "content": prompt}],
        max_tokens=1200,
        temperature=0,
    )
    return reply.text or ""


def _parse_company_list(text: str) -> list[Any]:
    start = text.find("[")
    end = text.rfind("]")
    if start < 0 or end < start:
        raise ValueError("The model did not return a company list.")
    parsed = json.loads(text[start : end + 1])
    if not isinstance(parsed, list):
        raise ValueError("The model did not return a company list.")
    return parsed


def _offer(
    extracted: list[dict[str, Any]],
    snippets: list[dict[str, str]],
    top_n: int,
    db_path: Any,
) -> list[dict[str, Any]]:
    evidence = " ".join(
        f"{item.get('title', '')} {item.get('content', '')} {item.get('url', '')}" for item in snippets
    ).lower()
    offered: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in extracted:
        name = str(row.get("company_name") or row.get("name") or "").strip()
        key = _name_key(name)
        if not key or key in seen or key not in evidence:
            continue
        seen.add(key)
        if _already_known(db_path, key):
            continue
        company = {
            "company_name": name,
            "website": _own_website(name, str(row.get("website") or "")),
            "industry": str(row.get("industry") or "").strip().lower(),
            "employee_count": _employee_count(row.get("employee_count")),
            "funding_stage": str(row.get("funding_stage") or "").strip().lower(),
            "why": str(row.get("why") or "").strip(),
        }
        offered.append(company)
        if len(offered) >= top_n:
            break
    _drop_shared_sites(offered)
    for company in offered:
        _queue(db_path, company)
    return offered


def _own_website(name: str, website: str) -> str:
    """Keep a site only when its address names this company."""
    url = website.strip()
    if "://" not in url:
        return ""
    host = urlparse(url).netloc.lower().removeprefix("www.")
    compact = re.sub(r"[^a-z0-9]", "", host)
    tokens = [part for part in re.findall(r"[a-z0-9]+", name.lower()) if len(part) > 3]
    if compact and any(token in compact for token in tokens):
        return url
    return ""


def _drop_shared_sites(companies: list[dict[str, Any]]) -> None:
    """A list page is not each company's site."""
    counts: dict[str, int] = {}
    for company in companies:
        site = company.get("website") or ""
        if site:
            counts[site] = counts.get(site, 0) + 1
    for company in companies:
        if counts.get(company.get("website") or "", 0) > 1:
            company["website"] = ""


def _name_key(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", name.lower()).strip()


def _employee_count(value: Any) -> int:
    try:
        count = int(value)
    except (TypeError, ValueError):
        return 0
    return count if count > 0 else 0


def _already_known(db_path: Any, name_key: str) -> bool:
    if not db_path:
        return False
    from desk_settings import list_icp_seed

    for row in list_icp_seed(db_path):
        if _name_key(str(row.get("company_name") or "")) == name_key:
            return True
    return _source_exists(db_path, f"icp-candidate:{name_key}")


def _source_exists(db_path: Any, source_key: str) -> bool:
    import sqlite3

    from runtime import resolve_db_path

    resolved = resolve_db_path(db_path)
    conn = sqlite3.connect(resolved, timeout=30.0)
    try:
        row = conn.execute(
            "SELECT 1 FROM pending_actions WHERE source_key = ?",
            (source_key,),
        ).fetchone()
    except sqlite3.OperationalError:
        return False
    finally:
        conn.close()
    return row is not None


def _queue(db_path: Any, company: dict[str, Any]) -> None:
    from priority_inbox import emit_priority_action

    name = company["company_name"]
    why = company["why"] or "Matches the ICP criteria."
    emit_priority_action(
        kind="icp_candidate",
        title=name,
        description=why,
        payload=company,
        priority=1,
        source_key=f"icp-candidate:{_name_key(name)}",
        db_path=str(db_path or "khursheed.db"),
    )
