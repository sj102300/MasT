"""Configuration loading (config.yaml)."""
from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field


class LLMConfig(BaseModel):
    provider: Literal["anthropic", "openai_compat"] = "anthropic"
    model: str = "claude-opus-5-5"
    # API key is read from this environment variable; never stored in the file.
    api_key_env: str = "ANTHROPIC_API_KEY"
    # Endpoint override. Required for openai_compat (e.g. https://llm.internal/v1).
    base_url: str | None = None
    max_tokens: int = 32000
    timeout_sec: float = 600
    max_retries: int = 2
    # anthropic only: thinking effort (low|medium|high|xhigh|max).
    effort: str | None = "high"
    # anthropic only: server-side refusal fallback ("default" or null to disable).
    fallbacks: str | None = "default"
    # openai_compat only: sampling temperature. null = server default.
    temperature: float | None = 0.2
    # TLS: path to a CA bundle (in-house certs) or false to disable verification.
    ca_bundle: str | None = None
    verify_ssl: bool = True
    # HTTP(S) proxy URL. null = use environment (HTTPS_PROXY).
    proxy: str | None = None


class LLMOverride(BaseModel):
    """Per-agent override; unset fields fall back to the global llm section."""

    provider: Literal["anthropic", "openai_compat"] | None = None
    model: str | None = None
    api_key_env: str | None = None
    base_url: str | None = None
    max_tokens: int | None = None
    effort: str | None = None
    temperature: float | None = None


class RunConfig(BaseModel):
    output_dir: str = "runs"
    framework: str = "gtest"
    # Language for human-readable fields (test descriptions, reports).
    language: str = "Korean"
    max_fix_iterations: int = 3
    test_timeout_sec: float = 120
    build_timeout_sec: float = 1800


class BuildConfig(BaseModel):
    # auto: vcxproj when --project is a .vcxproj (or one exists on Windows), else cmake
    system: Literal["auto", "cmake", "vcxproj"] = "auto"
    configuration: str = "Debug"
    platform: str = "x64"
    # vcxproj: override PlatformToolset (e.g. v143 when only VS2022 is installed)
    toolset: str | None = None
    msbuild_path: str | None = None
    # cmake: link this target from the project's CMakeLists.txt instead of compiling sources
    cmake_target: str | None = None
    cmake_generator: str | None = None
    cmake_args: list[str] = Field(default_factory=list)
    # Source selection when compiling product sources directly (globs, relative to project root).
    # Empty = vcxproj ClCompile list, or every C++ source under the project root (cmake).
    sources: list[str] = Field(default_factory=list)
    exclude: list[str] = Field(
        default_factory=lambda: ["build/**", "out/**", "**/test/**", "**/tests/**", "**/third_party/**"]
    )
    include_dirs: list[str] = Field(default_factory=list)
    defines: list[str] = Field(default_factory=list)
    libs: list[str] = Field(default_factory=list)
    lib_dirs: list[str] = Field(default_factory=list)
    # googletest source: local checkout (offline) or downloaded once into cache_dir
    gtest_source_dir: str | None = None
    gtest_url: str = "https://github.com/google/googletest/archive/refs/tags/v1.17.0.zip"
    cache_dir: str = "~/.mast/cache"
    ca_bundle: str | None = None


class AppConfig(BaseModel):
    llm: LLMConfig = Field(default_factory=LLMConfig)
    agents: dict[str, LLMOverride] = Field(default_factory=dict)
    run: RunConfig = Field(default_factory=RunConfig)
    build: BuildConfig = Field(default_factory=BuildConfig)

    def llm_for(self, agent: str) -> LLMConfig:
        override = self.agents.get(agent)
        if override is None:
            return self.llm
        data = self.llm.model_dump()
        data.update(override.model_dump(exclude_none=True))
        return LLMConfig(**data)


DEFAULT_CONFIG_NAMES = ("config.yaml", "config.yml")


def load_config(path: str | Path | None = None) -> AppConfig:
    """Load config from `path`, or from ./config.yaml if present, else defaults."""
    if path is None:
        for name in DEFAULT_CONFIG_NAMES:
            if Path(name).is_file():
                path = name
                break
        else:
            return AppConfig()
    text = Path(path).read_text(encoding="utf-8")
    data = yaml.safe_load(text) or {}
    return AppConfig.model_validate(data)
