"""Claude API client (official anthropic SDK)."""
from __future__ import annotations

import os

import anthropic

from ..config import LLMConfig
from .base import LLMError, LLMResponse, Message

FALLBACK_BETA = "server-side-fallback-2026-07-01"


class AnthropicClient:
    def __init__(self, cfg: LLMConfig):
        self.cfg = cfg
        api_key = os.environ.get(cfg.api_key_env) or None
        kwargs: dict = {
            "timeout": cfg.timeout_sec,
            "max_retries": cfg.max_retries,
        }
        if api_key:
            kwargs["api_key"] = api_key
        if cfg.base_url:
            kwargs["base_url"] = cfg.base_url
        verify = cfg.ca_bundle if cfg.ca_bundle else cfg.verify_ssl
        if verify is not True or cfg.proxy:
            kwargs["http_client"] = anthropic.DefaultHttpxClient(verify=verify, proxy=cfg.proxy)
        self.client = anthropic.Anthropic(**kwargs)

    def chat(self, system: str, messages: list[Message]) -> LLMResponse:
        params: dict = {
            "model": self.cfg.model,
            "max_tokens": self.cfg.max_tokens,
            "system": system,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "thinking": {"type": "adaptive"},
        }
        if self.cfg.effort:
            params["output_config"] = {"effort": self.cfg.effort}
        try:
            if self.cfg.fallbacks:
                with self.client.beta.messages.stream(
                    **params, betas=[FALLBACK_BETA], fallbacks=self.cfg.fallbacks
                ) as stream:
                    msg = stream.get_final_message()
            else:
                with self.client.messages.stream(**params) as stream:
                    msg = stream.get_final_message()
        except TypeError as e:
            if "authentication" not in str(e).lower():
                raise
            raise LLMError(f"No Claude API credentials: set the {self.cfg.api_key_env} environment variable") from e
        except anthropic.AuthenticationError as e:
            raise LLMError(f"Authentication failed (check ${self.cfg.api_key_env}): {e}") from e
        except anthropic.RateLimitError as e:
            raise LLMError(f"Rate limited: {e}") from e
        except anthropic.APIStatusError as e:
            raise LLMError(f"API error {e.status_code}: {e.message}") from e
        except anthropic.APIConnectionError as e:
            raise LLMError(f"Connection error: {e}") from e

        if msg.stop_reason == "refusal":
            raise LLMError("Request was declined by the model (stop_reason=refusal)")
        text = "".join(b.text for b in msg.content if b.type == "text")
        if msg.stop_reason == "max_tokens" and not text:
            raise LLMError("Response hit max_tokens before producing text; raise llm.max_tokens")
        return LLMResponse(
            text=text,
            model=msg.model,
            input_tokens=msg.usage.input_tokens,
            output_tokens=msg.usage.output_tokens,
            stop_reason=msg.stop_reason,
            raw=msg,
        )
