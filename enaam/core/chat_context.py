"""
Chat Context Manager - Manages conversation context and memory

Provides conversation state, history, and context awareness for multi-turn interactions.
"""

import json
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4

from .constants import DefaultValues
from .enums import ResponseStatus
from .logging import EnaamLogger


class ConversationTurn:
    """Represents a single turn in a conversation."""
    
    def __init__(
        self,
        user_input: str,
        assistant_response: Dict[str, Any],
        timestamp: Optional[datetime] = None,
        turn_id: Optional[str] = None
    ):
        self.turn_id = turn_id or str(uuid4())
        self.user_input = user_input
        self.assistant_response = assistant_response
        self.timestamp = timestamp or datetime.now(timezone.utc)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert turn to dictionary for storage."""
        return {
            "turn_id": self.turn_id,
            "user_input": self.user_input,
            "assistant_response": self.assistant_response,
            "timestamp": self.timestamp.isoformat()
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ConversationTurn":
        """Create turn from dictionary."""
        return cls(
            user_input=data["user_input"],
            assistant_response=data["assistant_response"],
            timestamp=datetime.fromisoformat(data["timestamp"]),
            turn_id=data["turn_id"]
        )


class ChatSession:
    """Represents a chat session with conversation history."""
    
    def __init__(
        self,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        created_at: Optional[datetime] = None
    ):
        self.session_id = session_id or str(uuid4())
        self.user_id = user_id or "default_user"
        self.created_at = created_at or datetime.now(timezone.utc)
        self.turns: List[ConversationTurn] = []
        self.context: Dict[str, Any] = {}
        self.last_activity = self.created_at
    
    def add_turn(self, user_input: str, assistant_response: Dict[str, Any]) -> ConversationTurn:
        """Add a new conversation turn."""
        turn = ConversationTurn(user_input, assistant_response)
        self.turns.append(turn)
        self.last_activity = datetime.now(timezone.utc)
        return turn
    
    def get_recent_turns(self, limit: int = 5) -> List[ConversationTurn]:
        """Get the most recent conversation turns."""
        return self.turns[-limit:] if self.turns else []
    
    def get_context_summary(self) -> Dict[str, Any]:
        """Get a summary of conversation context."""
        recent_turns = self.get_recent_turns(3)
        
        # Extract topics and actions from recent turns
        recent_topics = []
        recent_actions = []
        
        for turn in recent_turns:
            response = turn.assistant_response
            if "action" in response:
                recent_actions.append(response["action"])
            
            # Extract topics from user input (simple keyword extraction)
            user_words = turn.user_input.lower().split()
            business_keywords = ["email", "lead", "summary", "report", "digest", "task"]
            for keyword in business_keywords:
                if keyword in user_words and keyword not in recent_topics:
                    recent_topics.append(keyword)
        
        return {
            "session_id": self.session_id,
            "turn_count": len(self.turns),
            "recent_topics": recent_topics[-5:],  # Last 5 topics
            "recent_actions": recent_actions[-3:],  # Last 3 actions
            "last_activity": self.last_activity.isoformat(),
            "session_context": self.context
        }
    
    def set_context(self, key: str, value: Any) -> None:
        """Set a context value for this session."""
        self.context[key] = value
    
    def get_context(self, key: str, default: Any = None) -> Any:
        """Get a context value for this session."""
        return self.context.get(key, default)


class ChatContextManager:
    """
    Manages chat context, conversation history, and session state.
    
    Provides persistent storage for conversations and context-aware responses.
    """
    
    def __init__(
        self,
        db_path: Optional[str] = None,
        logger: Optional[EnaamLogger] = None
    ):
        self.db_path = db_path or str(Path("data") / "chat_context.db")
        self.logger = logger
        self._active_sessions: Dict[str, ChatSession] = {}
        self._session_timeout = DefaultValues.CHAT_SESSION_TIMEOUT
        self._init_database()
    
    def _init_database(self) -> None:
        """Initialize the SQLite database for persistent storage."""
        # Ensure data directory exists
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS chat_sessions (
                    session_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    last_activity TEXT NOT NULL,
                    context_data TEXT NOT NULL,
                    turn_count INTEGER DEFAULT 0
                )
            ''')
            
            conn.execute('''
                CREATE TABLE IF NOT EXISTS conversation_turns (
                    turn_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    user_input TEXT NOT NULL,
                    assistant_response TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    FOREIGN KEY (session_id) REFERENCES chat_sessions (session_id)
                )
            ''')
            
            conn.execute('''
                CREATE INDEX IF NOT EXISTS idx_session_activity 
                ON chat_sessions (last_activity)
            ''')
            
            conn.execute('''
                CREATE INDEX IF NOT EXISTS idx_turn_session 
                ON conversation_turns (session_id, timestamp)
            ''')
    
    def get_or_create_session(self, session_id: Optional[str] = None, user_id: Optional[str] = None) -> ChatSession:
        """Get existing session or create a new one."""
        if session_id and session_id in self._active_sessions:
            session = self._active_sessions[session_id]
            session.last_activity = datetime.now(timezone.utc)
            return session
        
        if session_id:
            # Try to load from database
            session = self._load_session_from_db(session_id)
            if session:
                self._active_sessions[session_id] = session
                return session
        
        # Create new session
        session = ChatSession(session_id=session_id, user_id=user_id)
        self._active_sessions[session.session_id] = session
        
        if self.logger:
            self.logger.debug("Created new chat session: %s", session.session_id)
        
        return session
    
    def add_conversation_turn(
        self,
        session_id: str,
        user_input: str,
        assistant_response: Dict[str, Any]
    ) -> ConversationTurn:
        """Add a new conversation turn to the session."""
        session = self.get_or_create_session(session_id)
        turn = session.add_turn(user_input, assistant_response)
        
        # Save to database
        self._save_turn_to_db(turn, session_id)
        self._update_session_in_db(session)
        
        if self.logger:
            self.logger.debug("Added turn to session %s: %s", session_id, turn.turn_id)
        
        return turn
    
    def get_conversation_context(self, session_id: str) -> Dict[str, Any]:
        """Get conversation context for enhanced responses."""
        session = self.get_or_create_session(session_id)
        context = session.get_context_summary()
        
        # Add enhanced context for better responses
        context["conversation_flow"] = self._analyze_conversation_flow(session)
        context["user_preferences"] = self._infer_user_preferences(session)
        
        return context
    
    def _analyze_conversation_flow(self, session: ChatSession) -> Dict[str, Any]:
        """Analyze conversation flow to understand user patterns."""
        if not session.turns:
            return {"pattern": "new_conversation"}
        
        recent_turns = session.get_recent_turns(5)
        
        # Check for repeated actions
        actions = [turn.assistant_response.get("action", "") for turn in recent_turns]
        repeated_action = max(set(actions), key=actions.count) if actions else None
        
        # Check for escalating complexity
        complexity_indicators = ["summary", "report", "analysis", "detailed"]
        is_escalating = any(
            indicator in turn.user_input.lower()
            for turn in recent_turns[-2:]
            for indicator in complexity_indicators
        )
        
        return {
            "pattern": "escalating" if is_escalating else "routine",
            "repeated_action": repeated_action,
            "conversation_length": len(session.turns),
            "engagement_level": "high" if len(session.turns) > 3 else "standard"
        }
    
    def _infer_user_preferences(self, session: ChatSession) -> Dict[str, Any]:
        """Infer user preferences from conversation history."""
        preferences = {
            "response_style": "standard",
            "detail_level": "standard",
            "preferred_actions": [],
            "time_of_day_patterns": []
        }
        
        if not session.turns:
            return preferences
        
        # Analyze preferred actions
        actions = [turn.assistant_response.get("action", "") for turn in session.turns]
        action_counts = {}
        for action in actions:
            if action:
                action_counts[action] = action_counts.get(action, 0) + 1
        
        # Sort by frequency
        preferences["preferred_actions"] = sorted(
            action_counts.items(), 
            key=lambda x: x[1], 
            reverse=True
        )[:3]
        
        # Analyze request complexity for detail level preference
        complex_keywords = ["detailed", "comprehensive", "full", "complete", "analysis"]
        simple_keywords = ["quick", "brief", "summary", "status"]
        
        complex_count = sum(
            1 for turn in session.turns
            for keyword in complex_keywords
            if keyword in turn.user_input.lower()
        )
        
        simple_count = sum(
            1 for turn in session.turns
            for keyword in simple_keywords
            if keyword in turn.user_input.lower()
        )
        
        if complex_count > simple_count:
            preferences["detail_level"] = "detailed"
        elif simple_count > complex_count:
            preferences["detail_level"] = "brief"
        
        return preferences
    
    def _save_turn_to_db(self, turn: ConversationTurn, session_id: str) -> None:
        """Save conversation turn to database."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute('''
                    INSERT INTO conversation_turns 
                    (turn_id, session_id, user_input, assistant_response, timestamp)
                    VALUES (?, ?, ?, ?, ?)
                ''', (
                    turn.turn_id,
                    session_id,
                    turn.user_input,
                    json.dumps(turn.assistant_response),
                    turn.timestamp.isoformat()
                ))
        except Exception as e:
            if self.logger:
                self.logger.error("Failed to save turn to database: %s", str(e))
    
    def _update_session_in_db(self, session: ChatSession) -> None:
        """Update session information in database."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute('''
                    INSERT OR REPLACE INTO chat_sessions
                    (session_id, user_id, created_at, last_activity, context_data, turn_count)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', (
                    session.session_id,
                    session.user_id,
                    session.created_at.isoformat(),
                    session.last_activity.isoformat(),
                    json.dumps(session.context),
                    len(session.turns)
                ))
        except Exception as e:
            if self.logger:
                self.logger.error("Failed to update session in database: %s", str(e))
    
    def _load_session_from_db(self, session_id: str) -> Optional[ChatSession]:
        """Load session from database."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute('''
                    SELECT user_id, created_at, last_activity, context_data
                    FROM chat_sessions WHERE session_id = ?
                ''', (session_id,))
                
                row = cursor.fetchone()
                if not row:
                    return None
                
                user_id, created_at, last_activity, context_data = row
                
                session = ChatSession(
                    session_id=session_id,
                    user_id=user_id,
                    created_at=datetime.fromisoformat(created_at)
                )
                session.last_activity = datetime.fromisoformat(last_activity)
                session.context = json.loads(context_data) if context_data else {}
                
                # Load conversation turns
                turn_cursor = conn.execute('''
                    SELECT turn_id, user_input, assistant_response, timestamp
                    FROM conversation_turns 
                    WHERE session_id = ?
                    ORDER BY timestamp
                ''', (session_id,))
                
                for turn_row in turn_cursor.fetchall():
                    turn_id, user_input, assistant_response_json, timestamp = turn_row
                    assistant_response = json.loads(assistant_response_json)
                    
                    turn = ConversationTurn(
                        user_input=user_input,
                        assistant_response=assistant_response,
                        timestamp=datetime.fromisoformat(timestamp),
                        turn_id=turn_id
                    )
                    session.turns.append(turn)
                
                return session
                
        except Exception as e:
            if self.logger:
                self.logger.error("Failed to load session from database: %s", str(e))
            return None
    
    def cleanup_old_sessions(self, max_age_hours: int = 24) -> int:
        """Clean up old sessions from memory and database."""
        cutoff_time = datetime.now(timezone.utc).timestamp() - (max_age_hours * 3600)
        cleaned_count = 0
        
        # Remove from active sessions
        expired_sessions = [
            session_id for session_id, session in self._active_sessions.items()
            if session.last_activity.timestamp() < cutoff_time
        ]
        
        for session_id in expired_sessions:
            del self._active_sessions[session_id]
            cleaned_count += 1
        
        # Optionally clean up database (keep for historical analysis)
        # For now, we keep all database records for analytics
        
        if self.logger and cleaned_count > 0:
            self.logger.info("Cleaned up %d expired chat sessions", cleaned_count)
        
        return cleaned_count
    
    def get_session_stats(self) -> Dict[str, Any]:
        """Get statistics about chat sessions."""
        active_count = len(self._active_sessions)
        
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute('SELECT COUNT(*) FROM chat_sessions')
                total_sessions = cursor.fetchone()[0]
                
                cursor = conn.execute('SELECT COUNT(*) FROM conversation_turns')
                total_turns = cursor.fetchone()[0]
                
                cursor = conn.execute('''
                    SELECT AVG(turn_count) FROM chat_sessions WHERE turn_count > 0
                ''')
                avg_turns = cursor.fetchone()[0] or 0
                
        except Exception:
            total_sessions = active_count
            total_turns = 0
            avg_turns = 0
        
        return {
            "active_sessions": active_count,
            "total_sessions": total_sessions,
            "total_conversation_turns": total_turns,
            "average_turns_per_session": round(avg_turns, 2)
        }