"""
Enaam State Management

Simple state tracking for agent operations.
"""

from dataclasses import dataclass
from dataclasses import field
from datetime import UTC
from datetime import datetime
from typing import Any, Dict, Optional


@dataclass
class EnaamState:
    """Minimal state container for Enaam operations"""
    
    current_request: Optional[str] = None
    last_action: Optional[str] = None
    session_data: Dict[str, Any] = field(default_factory=dict)
    request_count: int = 0
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    
    def update_request(self, request: str) -> None:
        """Update current request and increment counter"""
        self.current_request = request
        self.request_count += 1
        
    def set_last_action(self, action: str) -> None:
        """Record the last executed action"""
        self.last_action = action
        
    def get_session_data(self, key: str) -> Any:
        """Get session data by key"""
        return self.session_data.get(key)
        
    def set_session_data(self, key: str, value: Any) -> None:
        """Set session data"""
        self.session_data[key] = value
        
    def to_dict(self) -> Dict[str, Any]:
        """Convert state to dictionary"""
        return {
            "current_request": self.current_request,
            "last_action": self.last_action, 
            "session_data": self.session_data,
            "request_count": self.request_count,
            "created_at": self.created_at.isoformat()
        }