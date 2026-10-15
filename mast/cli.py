"""Command-line interface."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

import typer

from .config import load_config
from .llm import LLMError, Message, create_client

app = typer.Typer(add_completion=False, help="MasT: multi-agent C++ unit test generator")

ConfigOpt = typer.Option(None, "--config", "-c", help="Path to config.yaml")


def _utf8_stdout() -> None:
    # Windows consoles default to cp949/cp437; keep Korean/UTF-8 output readable.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


@app.callback()
def main() -> None:
    _utf8_stdout()


@app.command("check-llm")
def check_llm(config: Optional[Path] = ConfigOpt, agent: str = typer.Option("", help="Agent override to test")):
    """Send a short request to the configured LLM and print the reply."""
    cfg = load_config(config)
    llm_cfg = cfg.llm_for(agent) if agent else cfg.llm
    typer.echo(f"provider={llm_cfg.provider} model={llm_cfg.model} base_url={llm_cfg.base_url or '(default)'}")
    try:
        client = create_client(llm_cfg)
        resp = client.chat("Reply with exactly: OK", [Message("user", "ping")])
    except LLMError as e:
        typer.secho(f"FAILED: {e}", fg="red", err=True)
        raise typer.Exit(1)
    typer.secho(f"reply: {resp.text.strip()!r} (in={resp.input_tokens}, out={resp.output_tokens})", fg="green")


@app.command()
def analyze(
    target: Path = typer.Argument(..., exists=True, dir_okay=False, help="C++ source/header to analyze"),
    root: Optional[Path] = typer.Option(None, help="Project root (default: target's parent)"),
    include: list[Path] = typer.Option([], "--include", "-I", help="Extra dirs to look for the header/source pair"),
    as_json: bool = typer.Option(False, "--json", help="Print full JSON"),
    all_functions: bool = typer.Option(False, "--all", help="Include non-testable functions"),
):
    """Parse a C++ file (and its header/source pair) and list testable functions."""
    from .analyzer import analyze_target

    root = root or target.resolve().parent
    result = analyze_target(target, root, include)
    if as_json:
        typer.echo(result.model_dump_json(indent=2))
        return
    typer.echo("files: " + ", ".join(f.path for f in result.files))
    fns = result.functions if all_functions else result.testable_functions()
    for fn in fns:
        mark = "" if fn.is_testable else "  (skip)"
        typer.echo(f"  {fn.kind:8} {fn.qualified_name}{fn.parameters}{mark}")
    typer.echo(f"{len(result.testable_functions())} testable / {len(result.functions)} total")


if __name__ == "__main__":
    app()
