from pathlib import Path

import pytest

from mast.config import AppConfig, load_config
from mast.llm import FakeLLM, LLMError, Message, create_client, extract_json

ROOT = Path(__file__).resolve().parent.parent


def test_example_config_loads():
    cfg = load_config(ROOT / "config.example.yaml")
    assert cfg.llm.provider == "anthropic"
    assert cfg.run.max_fix_iterations == 3


def test_agent_override_merges():
    cfg = AppConfig.model_validate(
        {"llm": {"model": "base", "effort": "high"}, "agents": {"fixer": {"model": "big"}}}
    )
    fixer = cfg.llm_for("fixer")
    assert fixer.model == "big"
    assert fixer.effort == "high"
    assert cfg.llm_for("writer").model == "base"


def test_openai_compat_requires_base_url():
    cfg = AppConfig.model_validate({"llm": {"provider": "openai_compat", "model": "m"}})
    with pytest.raises(LLMError):
        create_client(cfg.llm)


def test_clients_construct(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    cfg = AppConfig()
    assert create_client(cfg.llm) is not None
    cfg2 = AppConfig.model_validate(
        {"llm": {"provider": "openai_compat", "model": "m", "base_url": "http://localhost:1/v1", "verify_ssl": False}}
    )
    assert create_client(cfg2.llm) is not None


@pytest.mark.parametrize(
    "text,expected",
    [
        ('{"a": 1}', {"a": 1}),
        ('here:\n```json\n{"a": 2}\n```\nbye', {"a": 2}),
        ('prefix {"a": 3} suffix', {"a": 3}),
        ("[1, 2]", [1, 2]),
    ],
)
def test_extract_json(text, expected):
    assert extract_json(text) == expected


def test_extract_json_fails():
    with pytest.raises(LLMError):
        extract_json("no json here")


def test_fake_llm():
    fake = FakeLLM(["one", "two"])
    assert fake.chat("s", [Message("user", "x")]).text == "one"
    assert fake.chat("s", []).text == "two"
    with pytest.raises(LLMError):
        fake.chat("s", [])
    assert len(fake.calls) == 3
