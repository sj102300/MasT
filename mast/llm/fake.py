"""Scripted LLM for tests and offline demos."""
from __future__ import annotations

from collections.abc import Callable

from .base import LLMError, LLMResponse, Message

Responder = Callable[[str, list[Message]], str]


class FakeLLM:
    """Returns queued replies in order, or delegates to a responder function."""

    def __init__(self, replies: list[str] | None = None, responder: Responder | None = None):
        self.replies = list(replies or [])
        self.responder = responder
        self.calls: list[tuple[str, list[Message]]] = []

    def chat(self, system: str, messages: list[Message]) -> LLMResponse:
        self.calls.append((system, list(messages)))
        if self.responder is not None:
            return LLMResponse(text=self.responder(system, messages), model="fake")
        if not self.replies:
            raise LLMError("FakeLLM has no more scripted replies")
        return LLMResponse(text=self.replies.pop(0), model="fake")
