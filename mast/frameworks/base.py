"""Test framework adapter interface (gtest now, in-house frameworks later)."""
from __future__ import annotations

from abc import ABC, abstractmethod


class TestFramework(ABC):
    name: str

    @abstractmethod
    def writer_rules(self) -> str:
        """Framework-specific rules appended to the Writer prompt."""

    @abstractmethod
    def file_header(self, includes: list[str]) -> str:
        """Lines every generated test file starts with."""
