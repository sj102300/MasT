"""Shared agent plumbing: prompt loading, LLM call logging, JSON/code extraction with retry."""
from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from importlib import resources
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from ..llm import LLMClient, LLMError, LLMResponse, Message, extract_json

T = TypeVar("T", bound=BaseModel)

_CODE_RE = re.compile(r"```(?:cpp|c\+\+|cc|cxx|c)?[ \t]*\r?\n(.*?)```", re.DOTALL)


def load_prompt(name: str, **values: str) -> str:
    text = resources.files("mast.prompts").joinpath(f"{name}.md").read_text(encoding="utf-8")
    for key, value in values.items():
        text = text.replace("{" + key + "}", value)
    return text


def extract_code_block(text: str) -> str:
    blocks = _CODE_RE.findall(text)
    if blocks:
        return max(blocks, key=len).strip() + "\n"
    stripped = text.strip()
    if "#include" in stripped:
        return stripped + "\n"
    raise LLMError("LLM response did not contain a code block")


class CallLog:
    """Appends every LLM exchange to a JSONL file for debugging."""

    def __init__(self, path: Path | None):
        self.path = path

    def write(self, agent: str, system: str, messages: list[Message], resp: LLMResponse | None,
              error: str | None, seconds: float) -> None:
        if self.path is None:
            return
        record = {
            "agent": agent,
            "seconds": round(seconds, 2),
            "model": resp.model if resp else "",
            "input_tokens": resp.input_tokens if resp else 0,
            "output_tokens": resp.output_tokens if resp else 0,
            "system": system,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "response": resp.text if resp else None,
            "error": error,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")


class Agent:
    name = "agent"

    def __init__(self, llm: LLMClient, log: CallLog | None = None, retries: int = 1):
        self.llm = llm
        self.log = log or CallLog(None)
        self.retries = retries
        self.usage = {"input_tokens": 0, "output_tokens": 0, "calls": 0}

    def _chat(self, system: str, messages: list[Message]) -> LLMResponse:
        start = time.monotonic()
        try:
            resp = self.llm.chat(system, messages)
        except LLMError as e:
            self.log.write(self.name, system, messages, None, str(e), time.monotonic() - start)
            raise
        self.log.write(self.name, system, messages, resp, None, time.monotonic() - start)
        self.usage["calls"] += 1
        self.usage["input_tokens"] += resp.input_tokens
        self.usage["output_tokens"] += resp.output_tokens
        return resp

    def _ask(self, system: str, user: str, parse: Callable[[str], T]) -> T:
        """Call the LLM and parse; on parse failure, send the error back and retry."""
        messages = [Message("user", user)]
        last_error = ""
        for _ in range(self.retries + 1):
            resp = self._chat(system, messages)
            try:
                return parse(resp.text)
            except (LLMError, ValidationError, ValueError) as e:
                last_error = str(e)
                messages = messages + [
                    Message("assistant", resp.text),
                    Message("user", f"Your reply could not be used: {last_error[:2000]}\n"
                                    "Reply again following the output format exactly."),
                ]
        raise LLMError(f"{self.name}: invalid response after {self.retries + 1} attempts: {last_error}")

    def ask_json(self, system: str, user: str, model: type[T]) -> T:
        return self._ask(system, user, lambda text: model.model_validate(extract_json(text)))

    def ask_code(self, system: str, user: str) -> str:
        return self._ask(system, user, extract_code_block)
