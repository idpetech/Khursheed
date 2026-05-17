from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict


class Skill(ABC):
    name: str

    @abstractmethod
    def run(self, task: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError
