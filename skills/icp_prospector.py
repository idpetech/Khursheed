"""
ICP Prospector Skill - Seed-list driven prospect research

Loads companies from CSV and enriches them with hiring signals,
CTO presence, and acquisition status using targeted searches.
"""

import csv
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List
from skills.base import Skill
from skills.tavily_client import tavily_search


logger = logging.getLogger(__name__)


class IcpProspectorSkill(Skill):
    name = "icp_prospector"

    def run(self, task: Dict[str, Any]) -> Dict[str, Any]:
        """Process seed companies and return ranked prospects"""
        payload = task.get("payload", {})
        
        # Extract configuration with defaults
        seed_path = payload.get("seed_path", "data/icp_seed.csv")
        industries = set(payload.get("industries", ["saas", "fintech", "edtech", "commerce"]))
        employee_min = payload.get("employee_min", 10)
        employee_max = payload.get("employee_max", 50)
        funding_stages = set(payload.get("funding_stages", ["seed", "series-a", "series-b"]))
        top_n = payload.get("top_n", 5)
        
        try:
            # Load and filter CSV data
            companies = self._load_and_filter_csv(
                seed_path, industries, employee_min, employee_max, funding_stages
            )
            
            if not companies:
                return {
                    "top_companies": [],
                    "rejected": [{"name": "No companies", "reason": "No valid companies found in seed data"}],
                    "seed_rows_scanned": 0
                }
            
            # Enrich companies with missing signals
            enriched_companies = self._enrich_companies(companies)
            
            # Rank companies using LLM or fallback heuristic
            ranked_result = self._rank_companies(enriched_companies, top_n)
            try:
                from open_loops import record_icp_companies

                record_icp_companies(
                    ranked_result.get("top_companies", []),
                    db_path=task.get("db_path", "khursheed.db"),
                )
            except Exception as loop_error:
                logger.warning("ICP prospector could not write open loops: %s", loop_error)

            return {
                **ranked_result,
                "seed_rows_scanned": len(companies)
            }
            
        except Exception as e:
            logger.error(f"ICP Prospector skill failed: {e}")
            return {
                "top_companies": [],
                "rejected": [{"name": "Error", "reason": str(e)}],
                "seed_rows_scanned": 0
            }

    def _load_and_filter_csv(
        self, 
        seed_path: str, 
        industries: set, 
        employee_min: int, 
        employee_max: int,
        funding_stages: set
    ) -> List[Dict[str, Any]]:
        """Load CSV and apply hard filters"""
        companies = []
        
        try:
            csv_path = Path(seed_path)
            if not csv_path.exists():
                logger.warning(f"Seed CSV not found: {seed_path}")
                return []
            
            with open(csv_path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                row_count = 0
                
                for row in reader:
                    row_count += 1
                    try:
                        # Apply hard filters
                        if not self._passes_hard_filters(row, industries, employee_min, employee_max, funding_stages):
                            continue
                        
                        # Clean and structure the data
                        company = {
                            "company_name": row.get("company_name", "").strip(),
                            "website": row.get("website", "").strip(),
                            "industry": row.get("industry", "").strip().lower(),
                            "employee_count": self._safe_int(row.get("employee_count")),
                            "funding_stage": row.get("funding_stage", "").strip().lower(),
                            "has_cto": row.get("has_cto", "").strip().lower(),
                            "acquired": row.get("acquired", "").strip().lower(),
                            "hiring_signals_url": row.get("hiring_signals_url", "").strip(),
                            "is_hiring_ai": "unknown"  # Will be enriched
                        }
                        
                        companies.append(company)
                        
                    except Exception as e:
                        logger.warning(f"Error processing CSV row {row_count}: {e}")
                        continue
            
            logger.info(f"Loaded {len(companies)} valid companies from {row_count} total rows")
            
        except Exception as e:
            logger.error(f"Error loading CSV {seed_path}: {e}")
            
        return companies

    def _passes_hard_filters(
        self, 
        row: Dict[str, str], 
        industries: set,
        employee_min: int, 
        employee_max: int,
        funding_stages: set
    ) -> bool:
        """Apply hard filters to determine if row should be kept"""
        try:
            # Industry filter
            industry = row.get("industry", "").strip().lower()
            if industry not in industries:
                return False
            
            # Employee count filter
            employee_count = self._safe_int(row.get("employee_count"))
            if employee_count is None or employee_count < employee_min or employee_count > employee_max:
                return False
            
            # Funding stage filter
            funding_stage = row.get("funding_stage", "").strip().lower()
            if funding_stage not in funding_stages:
                return False
            
            # Must NOT already have a CTO (we target companies that still need one).
            # Keep "no" and "unknown"; drop confirmed "yes".
            has_cto = row.get("has_cto", "").strip().lower()
            if has_cto == "yes":
                return False
            
            # Must NOT be acquired/merged. Keep "no" and "unknown"; drop confirmed "yes".
            acquired = row.get("acquired", "").strip().lower()
            if acquired == "yes":
                return False
            
            return True
            
        except Exception:
            return False

    def _safe_int(self, value: str | None) -> int | None:
        """Safely convert string to int"""
        if not value:
            return None
        try:
            return int(str(value).strip())
        except (ValueError, TypeError):
            return None

    def _enrich_companies(self, companies: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Enrich companies with missing signals via targeted searches"""
        enriched = []
        
        for company in companies:
            try:
                enriched_company = company.copy()
                
                # Enrich missing signals
                if company["has_cto"] == "unknown":
                    enriched_company["has_cto"] = self._check_has_cto(company["company_name"])
                
                if company["acquired"] == "unknown":
                    enriched_company["acquired"] = self._check_acquired(company["company_name"])
                
                if company["is_hiring_ai"] == "unknown":
                    enriched_company["is_hiring_ai"] = self._check_hiring_ai(company["company_name"])
                
                enriched.append(enriched_company)
                
            except Exception as e:
                logger.warning(f"Error enriching company {company.get('company_name', 'unknown')}: {e}")
                # Include original company data even if enrichment fails
                enriched.append(company)
        
        return enriched

    def _check_has_cto(self, company_name: str) -> str:
        """Check if company has a CTO via search"""
        try:
            query = f'"{company_name}" CTO "Chief Technology Officer"'
            results = tavily_search(query, max_results=3)
            
            if results and "results" in results:
                for result in results["results"]:
                    content = f"{result.get('title', '')} {result.get('content', '')}".lower()
                    if "cto" in content and company_name.lower() in content:
                        return "likely"
            
            return "unknown"
            
        except Exception as e:
            logger.warning(f"CTO check failed for {company_name}: {e}")
            return "unknown"

    def _check_acquired(self, company_name: str) -> str:
        """Check if company was acquired via search"""
        try:
            query = f'"{company_name}" acquired acquisition "acquired by"'
            results = tavily_search(query, max_results=3)
            
            if results and "results" in results:
                for result in results["results"]:
                    content = f"{result.get('title', '')} {result.get('content', '')}".lower()
                    if ("acquired" in content or "acquisition" in content) and company_name.lower() in content:
                        return "likely"
            
            return "unknown"
            
        except Exception as e:
            logger.warning(f"Acquisition check failed for {company_name}: {e}")
            return "unknown"

    def _check_hiring_ai(self, company_name: str) -> str:
        """Check if company is hiring AI/ML engineers via search"""
        try:
            query = f'"{company_name}" hiring "AI engineer" OR "ML engineer" OR "machine learning" OR "artificial intelligence"'
            results = tavily_search(query, max_results=3)
            
            if results and "results" in results:
                for result in results["results"]:
                    content = f"{result.get('title', '')} {result.get('content', '')}".lower()
                    if ("hiring" in content or "job" in content) and \
                       ("ai" in content or "machine learning" in content or "ml engineer" in content) and \
                       company_name.lower() in content:
                        return "likely"
            
            return "unknown"
            
        except Exception as e:
            logger.warning(f"AI hiring check failed for {company_name}: {e}")
            return "unknown"

    def _rank_companies(self, companies: List[Dict[str, Any]], top_n: int) -> Dict[str, Any]:
        """Rank companies using LLM or fallback heuristic"""
        openai_key = os.getenv("OPENAI_API_KEY")
        
        if openai_key:
            return self._rank_with_llm(companies, top_n, openai_key)
        else:
            return self._rank_with_heuristic(companies, top_n)

    def _rank_with_llm(self, companies: List[Dict[str, Any]], top_n: int, openai_key: str) -> Dict[str, Any]:
        """Rank companies using OpenAI LLM"""
        try:
            import openai
            
            client = openai.OpenAI(api_key=openai_key)
            
            # Prepare companies data for LLM
            companies_summary = []
            for i, company in enumerate(companies):
                companies_summary.append({
                    "index": i,
                    "name": company["company_name"],
                    "industry": company["industry"],
                    "employee_count": company["employee_count"],
                    "funding_stage": company["funding_stage"],
                    "has_cto": company["has_cto"],
                    "acquired": company["acquired"],
                    "is_hiring_ai": company["is_hiring_ai"]
                })
            
            prompt = f"""
            Analyze and rank these {len(companies)} companies as prospects for a FRACTIONAL CTO
            to offer services to.

            Ideal Customer Profile (higher rank = better fit):
            - Does NOT already have a CTO (has_cto = "no" is best; "unknown" is acceptable; "yes" is a poor fit).
            - Has NOT been acquired or merged (acquired = "no" is best; "unknown" acceptable; "yes" is disqualifying).
            - Is actively hiring AI / ML engineers (is_hiring_ai = "likely" is a strong positive signal).
            - Seed or early-series funding, 10-50 employees, in SaaS / FinTech / EdTech / Commerce.

            Companies: {json.dumps(companies_summary, indent=2)}

            Rank by ICP fit as described above (strongly reward NO existing CTO and NOT acquired).
            Return the top {top_n} companies in strict JSON format:
            
            {{
                "top_companies": [{{
                    "name": "company name",
                    "website": "website",
                    "industry": "industry",
                    "employee_count": number,
                    "funding_stage": "stage",
                    "has_cto": "yes/no/likely/unknown",
                    "acquired": "yes/no/likely/unknown",
                    "is_hiring_ai": "yes/no/likely/unknown",
                    "signal_confidence": {{"verified": [], "likely": [], "unknown": []}},
                    "rationale": "brief explanation",
                    "score": number
                }}],
                "rejected": [{{"name": "company", "reason": "why rejected"}}]
            }}
            
            Return ONLY valid JSON, no other text.
            """
            
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=2000,
                temperature=0.1
            )
            
            result_text = response.choices[0].message.content.strip()
            result = json.loads(result_text)
            
            # Enrich with original company data
            enriched_result = self._enrich_llm_result(result, companies)
            return enriched_result
            
        except Exception as e:
            logger.warning(f"LLM ranking failed, falling back to heuristic: {e}")
            return self._rank_with_heuristic(companies, top_n)

    def _rank_with_heuristic(self, companies: List[Dict[str, Any]], top_n: int) -> Dict[str, Any]:
        """Rank companies using simple heuristic scoring"""
        scored_companies = []
        
        for company in companies:
            score = 0
            
            # CTO absence scoring (ICP targets companies that still need a CTO).
            # "no" (confirmed no CTO) is best; "unknown" is a maybe; "likely"/"yes" means
            # they already have one -> no points.
            if company["has_cto"] == "no":
                score += 30
            elif company["has_cto"] == "unknown":
                score += 15
            
            # Not-acquired scoring (ICP excludes acquired/merged companies).
            if company["acquired"] == "no":
                score += 25
            elif company["acquired"] == "unknown":
                score += 10
            
            # AI hiring signals scoring
            if company["is_hiring_ai"] == "likely":
                score += 20
            
            # Industry scoring
            high_value_industries = ["fintech", "saas"]
            if company["industry"] in high_value_industries:
                score += 15
            
            # Employee count scoring (sweet spot)
            emp_count = company["employee_count"]
            if 20 <= emp_count <= 40:
                score += 10
            elif 10 <= emp_count <= 50:
                score += 5
            
            # Funding stage scoring
            if company["funding_stage"] in ["series-a", "series-b"]:
                score += 10
            
            company_with_score = company.copy()
            company_with_score.update({
                "score": score,
                "rationale": "llm_unavailable - scored using heuristic",
                "signal_confidence": {
                    "verified": [],
                    "likely": [k for k, v in company.items() if v == "likely"],
                    "unknown": [k for k, v in company.items() if v == "unknown"]
                }
            })
            
            scored_companies.append(company_with_score)
        
        # Sort by score and take top N
        sorted_companies = sorted(scored_companies, key=lambda x: x["score"], reverse=True)
        top_companies = sorted_companies[:top_n]
        rejected = [{"name": c["company_name"], "reason": f"Score {c['score']} below top {top_n}"} 
                   for c in sorted_companies[top_n:]]
        
        return {
            "top_companies": top_companies,
            "rejected": rejected
        }

    def _enrich_llm_result(self, llm_result: Dict[str, Any], original_companies: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Enrich LLM result with original company data"""
        try:
            # Create lookup dict for original data
            company_lookup = {c["company_name"]: c for c in original_companies}
            
            # Enrich top companies with original data
            enriched_top = []
            for company in llm_result.get("top_companies", []):
                original = company_lookup.get(company.get("name", ""))
                if original:
                    enriched = {**original, **company}
                    enriched_top.append(enriched)
            
            return {
                "top_companies": enriched_top,
                "rejected": llm_result.get("rejected", [])
            }
            
        except Exception as e:
            logger.warning(f"Error enriching LLM result: {e}")
            return llm_result