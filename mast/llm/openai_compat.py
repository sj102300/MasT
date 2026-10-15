"""OpenAI-compatible chat completions client (for in-house LLM gateways)."""
from __future__ import annotations

import os

import openai

from ..config import LLMConfig
from .base import LLMError, LLMResponse, Message


class OpenAICompatClient:
    def __init__(self, cfg: LLMConfig):
        if not cfg.base_url:
            raise LLMError("llm.base_url is required for provider openai_compat")
        self.cfg = cfg
        # Some gateways need no key; the SDK still requires a non-empty string.
        api_key = os.environ.get(cfg.api_key_env) or "none"
        kwargs: dict = {
            "api_key": api_key,
            "base_url": cfg.base_url,
            "timeout": cfg.timeout_sec,
            "max_retries": cfg.max_retries,
        }
        verify = cfg.ca_bundle if cfg.ca_bundle else cfg.verify_ssl
        if verify is not True or cfg.proxy:
            kwargs["http_client"] = openai.DefaultHttpxClient(verify=verify, proxy=cfg.proxy)
        self.client = openai.OpenAI(**kwargs)

    def chat(self, system: str, messages: list[Message]) -> LLMResponse:
        payload = [{"role": "system", "content": system}]
        payload += [{"role": m.role, "content": m.content} for m in messages]
        params: dict = {
            "model": self.cfg.model,
            "messages": payload,
            "max_tokens": self.cfg.max_tokens,
        }
        if self.cfg.temperature is not None:
            params["temperature"] = self.cfg.temperature
        try:
            resp = self.client.chat.completions.create(**params)
        except openai.AuthenticationError as e:
            raise LLMError(f"Authentication failed (check ${self.cfg.api_key_env}): {e}") from e
        except openai.RateLimitError as e:
            raise LLMError(f"Rate limited: {e}") from e
        except openai.APIStatusError as e:
            raise LLMError(f"API error {e.status_code}: {e.message}") from e
        except openai.APIConnectionError as e:
            raise LLMError(f"Connection error: {e}") from e

        if not resp.choices:
            raise LLMError("Empty response (no choices)")
        choice = resp.choices[0]
        usage = resp.usage
        return LLMResponse(
            text=choice.message.content or "",
            model=resp.model or self.cfg.model,
            input_tokens=getattr(usage, "prompt_tokens", 0) or 0,
            output_tokens=getattr(usage, "completion_tokens", 0) or 0,
            stop_reason=choice.finish_reason,
            raw=resp,
        )
