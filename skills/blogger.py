"""
Blogger Skill - Composite LLM-powered content generation with bias tempering

Generates blog posts using LLM as generator and InsightVault for bias tempering.
Supports draft and publish modes with LinkedIn integration.
"""

import json
import hashlib
import logging
import os
import requests
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from skills.base import Skill

logger = logging.getLogger(__name__)

# InsightVault MCP method name as constant for isolation
INSIGHT_VAULT_RETRIEVE_BIASES = "retrieve_biases"


class BloggerSkill(Skill):
    name = "blogger"

    def run(self, task: Dict[str, Any]) -> Dict[str, Any]:
        """Generate blog content with optional bias tempering"""
        try:
            payload = task.get("payload", {})
            ctx = task.get("ctx")
            
            # Extract configuration. Accept common aliases so a slightly
            # different payload shape still produces a draft instead of erroring.
            theme = (
                payload.get("theme")
                or payload.get("topic")
                or payload.get("subject")
                or payload.get("about")
            )
            if isinstance(theme, str):
                theme = theme.strip()

            tone = payload.get("tone", "executive, plainspoken, mildly contrarian")
            length = payload.get("length", "medium")
            sources = payload.get("sources", ["skill:cto_radar"])
            tempering = payload.get("tempering", "vault_preferred")
            cta = payload.get("cta")
            mode = payload.get("mode", "draft")

            # Resolve the theme. Explicit themes win; "auto" (or a missing theme)
            # triggers automatic selection: first a queued theme from the UI,
            # then one derived from the factual sources.
            theme_source = "explicit"
            if not theme or theme.lower() == "auto":
                theme, theme_source, auto_context = self._resolve_auto_theme(ctx, sources)
                if not theme:
                    return {
                        "status": "error",
                        "reason": "theme is required",
                        "hint": (
                            "Pass payload.theme (string) e.g. {'theme': 'fractional CTOs'}, "
                            "queue a theme in the UI, or ensure a source skill "
                            "(e.g. skill:cto_radar) returns results for theme='auto'."
                        ),
                    }
                # A queued theme may carry its own saved settings; honor them,
                # falling back to the payload/defaults above when absent.
                if auto_context:
                    tone = auto_context.get("tone", tone)
                    length = auto_context.get("length", length)
                    sources = auto_context.get("sources", sources)
                    cta = auto_context.get("cta", cta)
                    tempering = auto_context.get("tempering", tempering)
                    mode = auto_context.get("mode", mode)
                    if mode not in ["draft", "publish"]:
                        mode = "draft"
            self._theme_source = theme_source
            
            # Validate mode
            if mode not in ["draft", "publish"]:
                return {"status": "error", "reason": "mode must be 'draft' or 'publish'"}
            
            # Handle publish mode constraints
            if mode == "publish":
                # Check kill switch
                if not os.getenv("KHURSHEED_BLOGGER_PUBLISH_ENABLED", "").lower() in ["true", "1"]:
                    logger.info("Publish disabled by environment variable, demoting to draft")
                    mode = "draft"
                    return {
                        "status": "demoted_to_draft",
                        "reason": "publish_disabled",
                        **self._generate_draft(ctx, theme, tone, length, sources, tempering, cta)
                    }
                
                # Check LinkedIn credentials
                if not os.getenv("LINKEDIN_ACCESS_TOKEN") or not os.getenv("LINKEDIN_PAGE_ID"):
                    logger.warning("LinkedIn credentials missing, demoting to draft")
                    mode = "draft"
                    return {
                        "status": "demoted_to_draft", 
                        "reason": "linkedin_credentials_missing",
                        **self._generate_draft(ctx, theme, tone, length, sources, tempering, cta)
                    }
            
            # Generate content
            if mode == "draft":
                return self._generate_draft(ctx, theme, tone, length, sources, tempering, cta)
            else:
                return self._publish_post(ctx, theme, tone, length, sources, tempering, cta)
                
        except Exception as e:
            logger.error(f"Blogger skill failed: {e}")
            return {"status": "error", "reason": str(e)}

    def _generate_draft(
        self, ctx, theme: str, tone: str, length: str, sources: List[str], 
        tempering: str, cta: Optional[str]
    ) -> Dict[str, Any]:
        """Generate a draft blog post"""
        try:
            # Check vault requirement
            if tempering == "vault_required":
                if not ctx or not self._is_insight_vault_available(ctx):
                    self._emit_vault_offline_reminder(ctx, theme)
                    return {
                        "status": "degraded",
                        "reason": "insight_vault_unavailable"
                    }
            
            # Gather factual context from sources
            factual_context = self._gather_factual_context(ctx, sources)
            
            # Get biases if tempering enabled
            biases_data = None
            if tempering in ["vault_preferred", "vault_required"] and ctx:
                biases_data = self._retrieve_biases(ctx, theme)
            
            # Generate content using LLM
            draft = self._generate_content_with_llm(
                ctx, theme, tone, length, factual_context, biases_data, cta
            )
            
            if not draft:
                return {"status": "error", "reason": "content_generation_failed"}
            
            # Deterministically classify how strongly the draft was tempered by the
            # vault, overriding whatever the LLM self-reported.
            draft["bias_tempering"] = self._compute_bias_tempering(biases_data)
            
            # Create pending action for the draft
            action_id = self._create_draft_pending_action(draft, biases_data, theme)
            
            return {
                "status": "drafted",
                "action_id": action_id,
                "draft": draft,
                "theme": theme,
                "theme_source": getattr(self, "_theme_source", "explicit"),
                "bias_tempering": draft.get("bias_tempering", "untempered")
            }
            
        except Exception as e:
            logger.error(f"Draft generation failed: {e}")
            return {"status": "error", "reason": str(e)}

    def _publish_post(
        self, ctx, theme: str, tone: str, length: str, sources: List[str],
        tempering: str, cta: Optional[str]
    ) -> Dict[str, Any]:
        """Generate and publish a blog post to LinkedIn"""
        try:
            # Generate draft first
            draft_result = self._generate_draft(ctx, theme, tone, length, sources, tempering, cta)
            
            if draft_result.get("status") != "drafted":
                return draft_result
            
            draft = draft_result["draft"]
            
            # Attempt LinkedIn publish
            try:
                publish_result = self._publish_to_linkedin(draft)
                
                # Update pending action status
                if draft_result.get("action_id"):
                    self._update_pending_action_published(draft_result["action_id"])
                
                return {
                    "status": "published",
                    "draft": draft,
                    "linkedin_post_id": publish_result.get("id"),
                    "theme": theme,
                    "bias_tempering": draft.get("bias_tempering", "untempered")
                }
                
            except Exception as publish_error:
                logger.error(f"LinkedIn publish failed: {publish_error}")
                
                # Emit high-priority failure action
                self._emit_publish_failure_action(draft, str(publish_error))
                
                return {
                    "status": "demoted_to_draft",
                    "reason": "publish_failed", 
                    "error": str(publish_error),
                    **draft_result
                }
                
        except Exception as e:
            logger.error(f"Publish flow failed: {e}")
            return {"status": "error", "reason": str(e)}

    @staticmethod
    def _resolve_db_path(ctx) -> str:
        """Best-effort lookup of the active SQLite path from the context."""
        for attr_chain in (("db_path",), ("_manager", "_db_path")):
            obj = ctx
            try:
                for attr in attr_chain:
                    obj = getattr(obj, attr)
                if obj:
                    return str(obj)
            except AttributeError:
                continue
        return "khursheed.db"

    def _resolve_auto_theme(
        self, ctx, sources: List[str]
    ) -> tuple[Optional[str], str, Optional[Dict[str, Any]]]:
        """Pick a theme automatically.

        Precedence:
        1. The oldest pending theme queued by the user in the UI.
        2. A theme derived from the factual sources (e.g. top cto_radar hit).

        Returns (theme, theme_source, context). theme is None if nothing found.
        context carries any saved per-theme settings from the queue.
        """
        # 1) User-queued themes take priority.
        try:
            import blog_themes

            db_path = self._resolve_db_path(ctx)
            queued = blog_themes.next_pending_theme(db_path=db_path)
            if queued and queued.get("theme"):
                blog_themes.mark_used(queued["theme_id"], db_path=db_path)
                logger.info(f"Auto theme from queue: {queued['theme']}")
                return queued["theme"], "queued", queued.get("context")
        except Exception as e:
            logger.warning(f"Theme queue lookup failed: {e}")

        # 2) Derive from the factual sources.
        derived = self._derive_theme_from_sources(ctx, sources)
        if derived:
            return derived, "auto_sources", None

        return None, "auto_failed", None

    def _derive_theme_from_sources(self, ctx, sources: List[str]) -> Optional[str]:
        """Build a theme string from the first meaningful item a source returns."""
        if not ctx:
            return None
        for source in sources:
            if not source.startswith("skill:"):
                continue
            skill_name = source[6:]
            try:
                result = ctx.run_skill(skill_name, {})
            except Exception as e:
                logger.warning(f"Auto-theme source '{skill_name}' failed: {e}")
                continue

            headline = self._first_headline(result)
            if headline:
                logger.info(f"Derived theme from {skill_name}: {headline}")
                return headline
        return None

    @staticmethod
    def _first_headline(result: Any) -> Optional[str]:
        """Find a human-readable headline in a skill result dict."""
        if not isinstance(result, dict):
            return None
        # Known list-bearing keys across our skills, in priority order.
        list_keys = ["opportunities", "top_companies", "companies", "leads", "items"]
        item_keys = ["title", "company_name", "name", "headline", "role"]
        for lk in list_keys:
            items = result.get(lk)
            if isinstance(items, list) and items:
                first = items[0]
                if isinstance(first, dict):
                    for ik in item_keys:
                        val = first.get(ik)
                        if isinstance(val, str) and val.strip():
                            return val.strip()
                elif isinstance(first, str) and first.strip():
                    return first.strip()
        return None

    def _is_insight_vault_available(self, ctx) -> bool:
        """Check if InsightVault MCP service is available"""
        try:
            vault = ctx.mcp("insight_vault")
            return vault.available()
        except Exception as e:
            logger.warning(f"InsightVault availability check failed: {e}")
            return False

    def _gather_factual_context(self, ctx, sources: List[str]) -> str:
        """Gather factual context from specified sources"""
        context_parts = []
        
        for source in sources:
            try:
                if source.startswith("skill:"):
                    skill_name = source[6:]  # Remove "skill:" prefix
                    if ctx:
                        result = ctx.run_skill(skill_name, {})
                        context_parts.append(f"From {skill_name}: {json.dumps(result)}")
                    else:
                        logger.warning(f"No context available to run skill: {skill_name}")
                else:
                    logger.warning(f"Unknown source type: {source}")
                    
            except Exception as e:
                logger.warning(f"Failed to gather context from source '{source}': {e}")
                continue
        
        return "\n\n".join(context_parts) if context_parts else "No factual context available."

    def _retrieve_biases(self, ctx, theme: str) -> Optional[Dict[str, Any]]:
        """Retrieve biases from InsightVault"""
        try:
            vault = ctx.mcp("insight_vault")
            if not vault.available():
                logger.warning("InsightVault not available for bias retrieval")
                return None
            
            params = {
                "theme": theme,
                "limit": 10,
                "include_kinds": [
                    "opinion", "bias", "preference", 
                    "contrarian_take", "pet_peeve", "non_negotiable"
                ]
            }
            
            result = vault.request(INSIGHT_VAULT_RETRIEVE_BIASES, params)
            logger.info(f"Retrieved {len(result.get('items', []))} biases for theme '{theme}'")
            return result
            
        except Exception as e:
            logger.warning(f"Failed to retrieve biases from InsightVault: {e}")
            return None

    def _generate_content_with_llm(
        self, ctx, theme: str, tone: str, length: str, factual_context: str,
        biases_data: Optional[Dict[str, Any]], cta: Optional[str]
    ) -> Optional[Dict[str, Any]]:
        """Generate content using OpenAI LLM"""
        try:
            if not ctx:
                logger.error("No context available for LLM access")
                return None
                
            llm = ctx.llm()
            if not llm:
                logger.error("LLM not available")
                return None
            
            # Partition biases by strength
            biases_by_strength = self._partition_biases(biases_data)
            
            # Build system prompt with bias instructions
            system_prompt = self._build_system_prompt(tone, length, biases_by_strength)
            
            # Build user prompt
            user_prompt = self._build_user_prompt(theme, factual_context, cta)
            
            # Generate content
            response = llm.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                max_tokens=2000,
                temperature=0.7
            )
            
            content = response.choices[0].message.content.strip()
            
            # Parse JSON response
            try:
                draft = json.loads(content)
                
                # Validate required fields
                required_fields = ["title", "body_markdown", "hashtags", "word_count", "bias_tempering"]
                if not all(field in draft for field in required_fields):
                    logger.error(f"LLM response missing required fields: {required_fields}")
                    return None
                
                return draft
                
            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse LLM response as JSON: {e}")
                return None
                
        except Exception as e:
            logger.error(f"LLM content generation failed: {e}")
            return None

    def _compute_bias_tempering(self, biases_data: Optional[Dict[str, Any]]) -> str:
        """Classify how strongly the vault shaped the draft.

        - "tempered": >= 3 items AND theme_match_score >= 0.5
        - "lightly_tempered": some items, but few or low match
        - "untempered": vault unavailable / disabled / no relevant items
        """
        if not biases_data:
            return "untempered"
        items = biases_data.get("items", []) or []
        if not items:
            return "untempered"
        match_score = biases_data.get("theme_match_score", 0) or 0
        if len(items) >= 3 and match_score >= 0.5:
            return "tempered"
        return "lightly_tempered"

    def _partition_biases(self, biases_data: Optional[Dict[str, Any]]) -> Dict[str, List[Dict]]:
        """Partition biases by strength level"""
        partitioned = {
            "non_negotiable": [],
            "firm": [],
            "soft": []
        }
        
        if not biases_data or "items" not in biases_data:
            return partitioned
        
        for bias in biases_data["items"]:
            strength = bias.get("strength", "soft")
            if strength in partitioned:
                partitioned[strength].append(bias)
        
        return partitioned

    def _build_system_prompt(self, tone: str, length: str, biases_by_strength: Dict[str, List]) -> str:
        """Build system prompt with bias tempering instructions"""
        length_words = {
            "short": "300-500 words",
            "medium": "500-800 words", 
            "long": "800-1200 words"
        }
        
        target_length = length_words.get(length, "500-800 words")
        
        prompt = f"""You are an expert content creator generating a LinkedIn post with tone: {tone}
Target length: {target_length}

BIAS TEMPERING INSTRUCTIONS:
"""
        
        if biases_by_strength["non_negotiable"]:
            prompt += "\nNON-NEGOTIABLE RULES (must follow strictly):\n"
            for bias in biases_by_strength["non_negotiable"]:
                prompt += f"- {bias.get('text', 'Unknown bias')}\n"
        
        if biases_by_strength["firm"]:
            prompt += "\nSTRONG PREFERENCES (strongly favor unless compelling reason):\n"
            for bias in biases_by_strength["firm"]:
                prompt += f"- {bias.get('text', 'Unknown bias')}\n"
        
        if biases_by_strength["soft"]:
            prompt += "\nSOFT SUGGESTIONS (consider when relevant):\n"
            for bias in biases_by_strength["soft"]:
                prompt += f"- {bias.get('text', 'Unknown bias')}\n"
        
        has_biases = any(biases_by_strength.values())
        tempering_level = "tempered" if has_biases else "untempered"
        
        prompt += f"""
Use these biases as a LENS to shape your perspective, not verbatim quotes.
Return ONLY valid JSON in this exact format:
{{
  "title": "Compelling post title",
  "body_markdown": "Full post content in markdown format",
  "hashtags": ["hashtag1", "hashtag2", "hashtag3"],
  "suggested_image_prompt": "Brief description for AI image generation",
  "word_count": actual_word_count,
  "bias_tempering": "{tempering_level}",
  "biases_applied": [list of bias IDs that influenced content],
  "biases_overridden": [{{"id": "bias_id", "reason": "why overridden"}}]
}}
"""
        
        return prompt

    def _build_user_prompt(self, theme: str, factual_context: str, cta: Optional[str]) -> str:
        """Build user prompt with theme and context"""
        prompt = f"Generate a substantive LinkedIn post about: {theme}\n\n"
        
        if factual_context and factual_context != "No factual context available.":
            prompt += f"Factual context to incorporate:\n{factual_context}\n\n"
        
        if cta:
            prompt += f"Include this call-to-action: {cta}\n\n"
        
        prompt += "Create engaging, thoughtful content that provides value to readers."
        
        return prompt

    def _create_draft_pending_action(
        self, draft: Dict[str, Any], biases_data: Optional[Dict[str, Any]], theme: str
    ) -> str:
        """Create pending action for the draft"""
        try:
            if not hasattr(self, 'priority_inbox'):
                # Import priority_inbox if not available via context
                import priority_inbox as pi
            else:
                pi = self.priority_inbox
                
            # Create source key for deduplication
            iso_date = datetime.now(timezone.utc).date().isoformat()
            source_key = hashlib.sha256(f"{theme}{iso_date}".encode()).hexdigest()
            
            # Prefix title if untempered
            title = draft["title"]
            if draft.get("bias_tempering") == "untempered":
                title = f"[UNTEMPERED] {title}"
            
            # Build payload with draft and biases
            payload = {
                **draft,
                "theme": theme,
                "retrieved_biases": biases_data
            }
            
            action_id = pi.emit_priority_action(
                kind="linkedin_post_draft",
                title=title,
                description=f"Generated blog post draft for theme: {theme}",
                payload=payload,
                priority=1,
                source_key=source_key
            )
            
            logger.info(f"Created draft pending action: {action_id}")
            return action_id
            
        except Exception as e:
            logger.error(f"Failed to create draft pending action: {e}")
            return "unknown"

    def _publish_to_linkedin(self, draft: Dict[str, Any]) -> Dict[str, Any]:
        """Publish draft to LinkedIn"""
        access_token = os.getenv("LINKEDIN_ACCESS_TOKEN")
        page_id = os.getenv("LINKEDIN_PAGE_ID")
        
        if not access_token or not page_id:
            raise ValueError("LinkedIn credentials not configured")
        
        # Build LinkedIn post payload
        post_payload = {
            "author": f"urn:li:organization:{page_id}",
            "lifecycleState": "PUBLISHED",
            "specificContent": {
                "com.linkedin.ugc.ShareContent": {
                    "shareCommentary": {
                        "text": f"{draft['title']}\n\n{draft['body_markdown']}\n\n{' '.join(f'#{tag}' for tag in draft.get('hashtags', []))}"
                    },
                    "shareMediaCategory": "NONE"
                }
            },
            "visibility": {
                "com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"
            }
        }
        
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "X-Restli-Protocol-Version": "2.0.0"
        }
        
        response = requests.post(
            "https://api.linkedin.com/v2/ugcPosts",
            headers=headers,
            json=post_payload,
            timeout=30
        )
        
        if response.status_code not in [200, 201]:
            raise RuntimeError(f"LinkedIn API error {response.status_code}: {response.text}")
        
        return response.json()

    def _emit_vault_offline_reminder(self, ctx, theme: str) -> None:
        """Emit priority action for vault offline"""
        try:
            if ctx and hasattr(ctx, 'priority_inbox') and ctx.priority_inbox:
                pi = ctx.priority_inbox
                
                pi.emit_priority_action(
                    kind="insight_vault_offline_reminder",
                    title="InsightVault Offline - Blog Tempering Unavailable",
                    description=f"Cannot generate tempered content for theme '{theme}' - InsightVault MCP service unavailable",
                    payload={"theme": theme, "required_for": "blog_tempering"},
                    priority=1,
                    source_key=f"vault_offline_reminder_{theme}"
                )
                
        except Exception as e:
            logger.error(f"Failed to emit vault offline reminder: {e}")

    def _emit_publish_failure_action(self, draft: Dict[str, Any], error: str) -> None:
        """Emit high-priority action for publish failure"""
        try:
            import priority_inbox as pi
            
            pi.emit_priority_action(
                kind="linkedin_post_failed",
                title=f"LinkedIn Publish Failed: {draft.get('title', 'Unknown')}",
                description=f"Failed to publish blog post to LinkedIn: {error}",
                payload={"draft": draft, "error": error},
                priority=2,
                source_key=f"linkedin_fail_{hashlib.sha256(draft.get('title', 'unknown').encode()).hexdigest()[:8]}"
            )
            
        except Exception as e:
            logger.error(f"Failed to emit publish failure action: {e}")

    def _update_pending_action_published(self, action_id: str) -> None:
        """Update pending action status to published"""
        try:
            import sqlite3
            
            conn = sqlite3.connect("khursheed.db", timeout=30.0)
            conn.execute(
                "UPDATE pending_actions SET status = 'executed', executed_at = ? WHERE action_id = ?",
                (datetime.now(timezone.utc).isoformat(), action_id)
            )
            conn.commit()
            conn.close()
            
        except Exception as e:
            logger.warning(f"Failed to update pending action status: {e}")