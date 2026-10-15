from ..config import LLMConfig
from .base import LLMClient, LLMError, LLMResponse, Message, extract_json
from .fake import FakeLLM


def create_client(cfg: LLMConfig) -> LLMClient:
    if cfg.provider == "anthropic":
        from .anthropic_client import AnthropicClient

        return AnthropicClient(cfg)
    if cfg.provider == "openai_compat":
        from .openai_compat import OpenAICompatClient

        return OpenAICompatClient(cfg)
    raise LLMError(f"Unknown llm.provider: {cfg.provider}")


__all__ = [
    "FakeLLM",
    "LLMClient",
    "LLMError",
    "LLMResponse",
    "Message",
    "create_client",
    "extract_json",
]
