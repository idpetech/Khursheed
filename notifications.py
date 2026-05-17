from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path


class Notifier(ABC):
    @abstractmethod
    def send(self, content: str) -> str:
        raise NotImplementedError


class MarkdownFileNotifier(Notifier):
    def __init__(self, path: str = "executive_summary.md") -> None:
        self._path = Path(path)

    def send(self, content: str) -> str:
        self._path.write_text(content)
        return str(self._path)
