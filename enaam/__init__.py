"""
Enaam - Chief of Staff AI System

A lightweight cognitive capture and operational knowledge system.
"""

from .config import EnaamConfig
from .core.agent import EnaamAgent
from .core.container import ServiceContainer
from .core.container import get_default_container
from .core.logging import EnaamLogger
from .core.logging import create_logger
from .core.router import EnaamRouter
from .core.state import EnaamState


__version__ = "0.1.0"

__all__ = [
    "EnaamAgent",
    "EnaamLogger", 
    "create_logger",
    "ServiceContainer",
    "get_default_container",
    "EnaamState",
    "EnaamRouter",
    "EnaamConfig",
]