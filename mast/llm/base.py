"""Provider-neutral LLM interface."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Protocol


class LLMError(RuntimeError):
    pass


@dataclass
class Message:
    role: str  # "user" | "assistant"
    content: str


@dataclass
class LLMResponse:
    text: str
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    stop_reason: str | None = None
    raw: Any = field(default=None, repr=False)


class LLMClient(Protocol):
    def chat(self, system: str, messages: list[Message]) -> LLMResponse: ...


_FENCE_RE = re.compile(r"```(?:json)?\s*\n(.*?)```", re.DOTALL)


def extract_json(text: str) -> Any:
    """Parse JSON from an LLM reply: bare JSON, a ```json fence, or the first {...} span."""
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    for block in _FENCE_RE.findall(text):
        try:
            return json.loads(block)
        except json.JSONDecodeError:
            continue
    for open_ch, close_ch in (("{", "}"), ("[", "]")):
        start, end = text.find(open_ch), text.rfind(close_ch)
        if start != -1 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                continue
    raise LLMError("LLM response did not contain valid JSON")
