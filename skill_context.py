"""
Skill Context - Future-extensibility kernel for composite skills

Provides a context object that skills can use to:
- Call other skills recursively
- Access MCP services 
- Get shared LLM client
- Access priority inbox functionality
"""

import logging
import os
from typing import Any, Dict, TYPE_CHECKING

if TYPE_CHECKING:
    from manager import Manager
    from mcp_registry import MCPRegistry, MCPHandle

logger = logging.getLogger(__name__)


class SkillContext:
    """
    Context object passed to skills for accessing shared services.
    
    Provides controlled access to:
    - Manager for skill invocation
    - MCP services
    - Shared OpenAI client
    - Priority inbox functionality
    """
    
    def __init__(self, manager: 'Manager', mcp_registry: 'MCPRegistry'):
        self._manager = manager
        self._mcp_registry = mcp_registry
        self._depth = 0
        self._max_depth = 3
        self._llm_client = None
        
        # Import priority_inbox module for access
        try:
            import priority_inbox
            self.priority_inbox = priority_inbox
        except ImportError:
            logger.warning("priority_inbox module not available")
            self.priority_inbox = None

    def run_skill(self, name: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Run another skill with recursion depth protection.
        
        Args:
            name: Skill name to execute
            payload: Payload data for the skill
            
        Returns:
            Result from the skill execution
            
        Raises:
            RuntimeError: If max recursion depth exceeded
            KeyError: If skill not found
        """
        if self._depth >= self._max_depth:
            raise RuntimeError(f"Skill recursion depth limit ({self._max_depth}) exceeded")
        
        try:
            # Create a child context with incremented depth
            child_context = SkillContext(self._manager, self._mcp_registry)
            child_context._depth = self._depth + 1
            child_context._llm_client = self._llm_client
            
            # Generate a unique task ID for the recursive call
            import uuid
            task_id = f"recursive-{uuid.uuid4().hex[:8]}"
            
            # Build task with child context
            task = {
                "id": task_id,
                "payload": payload,
                "skills": [name],
                "ctx": child_context,
                "db_path": str(self._manager._db_path),
            }
            
            # Use manager's internal skill execution
            skill = self._manager._skills.get(name)
            if skill is None:
                raise KeyError(f"Skill '{name}' is not registered")
            
            logger.info(f"Executing skill '{name}' at depth {self._depth + 1}")
            result = skill.run(task)
            
            # Record the run
            self._manager._record_run(task_id, name, result)
            
            return result
            
        except Exception as e:
            logger.error(f"Error in recursive skill call '{name}': {e}")
            raise

    def mcp(self, alias: str) -> 'MCPHandle':
        """
        Get MCP handle by alias.
        
        Args:
            alias: MCP service alias (e.g., 'insight_vault')
            
        Returns:
            MCPHandle for the service
            
        Raises:
            KeyError: If alias not found in registry
        """
        return self._mcp_registry.get_handle(alias)

    def llm(self):
        """
        Get shared OpenAI client instance.
        
        Returns:
            OpenAI client or None if not available
        """
        if self._llm_client is None:
            openai_key = os.getenv("OPENAI_API_KEY")
            if openai_key:
                try:
                    import openai
                    self._llm_client = openai.OpenAI(api_key=openai_key)
                except ImportError:
                    logger.warning("OpenAI package not available")
                    return None
            else:
                logger.warning("OPENAI_API_KEY not set")
                return None
        
        return self._llm_client

    def _set_depth(self, depth: int) -> None:
        """Internal method to set recursion depth"""
        self._depth = depth