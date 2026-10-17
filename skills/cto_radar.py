"""
CTO Radar Skill - Identifies fractional/interim CTO opportunities

Searches for fractional CTO positions with intelligent scoring based on
location, work mode, and industry relevance.
"""

import logging
from typing import Any, Dict, List
from skills.base import Skill
from skills.tavily_client import tavily_search


logger = logging.getLogger(__name__)


class CtoRadarSkill(Skill):
    name = "cto_radar"

    def run(self, task: Dict[str, Any]) -> Dict[str, Any]:
        """Search for fractional CTO opportunities and score them"""
        try:
            # Define search queries for fractional CTO opportunities
            queries = [
                '"fractional CTO" remote United States',
                '"part-time CTO" remote United States',
                '"interim CTO" remote United States',
                '"fractional CTO" Jacksonville FL hybrid OR remote',
                '"fractional CTO" startup Florida remote'
            ]
            
            all_opportunities = []
            
            # Execute each search query
            for query in queries:
                try:
                    logger.info(f"Searching for: {query}")
                    results = tavily_search(query, max_results=8)
                    
                    # Process search results
                    if results and "results" in results:
                        for result in results["results"]:
                            opportunity = self._process_search_result(result)
                            if opportunity:
                                all_opportunities.append(opportunity)
                                
                except Exception as e:
                    logger.warning(f"Search failed for query '{query}': {e}")
                    continue
            
            # Remove duplicates based on URL
            unique_opportunities = self._deduplicate_by_url(all_opportunities)
            
            # Sort by score (highest first) and return top 10
            top_opportunities = sorted(unique_opportunities, key=lambda x: x["score"], reverse=True)[:10]
            try:
                from open_loops import record_cto_opportunities

                record_cto_opportunities(
                    top_opportunities,
                    db_path=task.get("db_path", "khursheed.db"),
                )
            except Exception as loop_error:
                logger.warning("CTO radar could not write open loops: %s", loop_error)

            return {
                "opportunities": top_opportunities,
                "total_found": len(unique_opportunities),
                "queries_executed": len(queries)
            }
            
        except Exception as e:
            logger.error(f"CTO Radar skill failed: {e}")
            return {
                "opportunities": [],
                "total_found": 0,
                "queries_executed": 0,
                "error": str(e)
            }

    def _process_search_result(self, result: Dict[str, Any]) -> Dict[str, Any] | None:
        """Process a single search result and calculate score"""
        try:
            title = result.get("title", "")
            url = result.get("url", "")
            snippet = result.get("content", "")
            
            if not title or not url:
                return None
            
            # Extract location and work mode
            location, work_mode = self._extract_location_and_mode(title, snippet)
            
            # Calculate score
            score = self._calculate_score(title, snippet, location, work_mode)
            
            # Generate tags
            tags = self._generate_tags(title, snippet)
            
            return {
                "title": title,
                "url": url,
                "snippet": snippet[:200] + "..." if len(snippet) > 200 else snippet,
                "location": location,
                "work_mode": work_mode,
                "score": score,
                "tags": tags
            }
            
        except Exception as e:
            logger.warning(f"Error processing search result: {e}")
            return None

    def _extract_location_and_mode(self, title: str, snippet: str) -> tuple[str, str]:
        """Extract location and work mode from title and snippet"""
        text = f"{title} {snippet}".lower()
        
        # Detect work mode
        work_mode = "unknown"
        if "remote" in text:
            work_mode = "remote"
        elif "hybrid" in text:
            work_mode = "hybrid"
        elif "on-site" in text or "onsite" in text:
            work_mode = "on-site"
        
        # Detect location
        location = "unknown"
        if "jacksonville" in text:
            location = "Jacksonville, FL"
        elif "florida" in text:
            location = "Florida"
        elif "united states" in text or " us " in text or " usa " in text:
            location = "United States"
        
        return location, work_mode

    def _calculate_score(self, title: str, snippet: str, location: str, work_mode: str) -> int:
        """Calculate opportunity score based on criteria"""
        text = f"{title} {snippet}".lower()
        score = 0
        
        # Location and work mode scoring
        if (work_mode == "remote" and "united states" in location.lower()) or \
           ("jacksonville" in location.lower() and work_mode in ["hybrid", "remote"]):
            score += 60
        
        # Role type scoring
        if any(term in text for term in ["fractional", "part-time", "interim"]):
            score += 30
        
        # Industry persona hits
        persona_industries = ["sap", "supply chain", "fintech", "healthtech", "health tech"]
        if any(industry in text for industry in persona_industries):
            score += 20
        
        # Negative scoring
        if "full-time" in text or "full time" in text:
            score -= 50
        if "on-site only" in text or "onsite only" in text:
            score -= 50
        
        return max(0, score)  # Ensure non-negative score

    def _generate_tags(self, title: str, snippet: str) -> List[str]:
        """Generate relevant tags for the opportunity"""
        text = f"{title} {snippet}".lower()
        tags = []
        
        # Role type tags
        if "fractional" in text:
            tags.append("fractional")
        if "part-time" in text or "part time" in text:
            tags.append("part-time")
        if "interim" in text:
            tags.append("interim")
        
        # Work mode tags
        if "remote" in text:
            tags.append("remote")
        if "hybrid" in text:
            tags.append("hybrid")
        
        # Industry tags
        if "startup" in text:
            tags.append("startup")
        if "saas" in text:
            tags.append("saas")
        if "fintech" in text:
            tags.append("fintech")
        if "healthtech" in text or "health tech" in text:
            tags.append("healthtech")
        
        # Experience level
        if "senior" in text:
            tags.append("senior")
        if "lead" in text:
            tags.append("leadership")
        
        return list(set(tags))  # Remove duplicates

    def _deduplicate_by_url(self, opportunities: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Remove duplicate opportunities based on URL"""
        seen_urls = set()
        unique_opportunities = []
        
        for opp in opportunities:
            url = opp.get("url", "")
            if url and url not in seen_urls:
                seen_urls.add(url)
                unique_opportunities.append(opp)
        
        return unique_opportunities