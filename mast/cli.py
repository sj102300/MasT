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


@app.command()
def generate(
    target: Path = typer.Argument(..., exists=True, dir_okay=False, help="C++ source/header to test"),
    root: Optional[Path] = typer.Option(None, help="Project root (default: target's parent)"),
    include: list[Path] = typer.Option([], "--include", "-I", help="Extra dirs to look for the header/source pair"),
    function: list[str] = typer.Option([], "--function", "-f", help="Only these functions (repeatable)"),
    config: Optional[Path] = ConfigOpt,
):
    """Analyze -> plan -> write tests for TARGET."""
    from .orchestrator import Pipeline, RunRequest

    cfg = load_config(config)
    root = (root or target.resolve().parent).resolve()

    def on_event(e):
        typer.echo(f"[{e.stage}] {e.message}")

    req = RunRequest(project_root=root, target=target.resolve(), functions=function, search_dirs=include)
    try:
        state = Pipeline(cfg, on_event).run(req)
    except (LLMError, ValueError) as e:
        typer.secho(f"FAILED: {e}", fg="red", err=True)
        raise typer.Exit(1)
    typer.secho(f"Run saved to {state.run_dir}", fg="green")


@app.command()
def selftest(
    project: Optional[Path] = typer.Option(None, help="Sample project (.vcxproj or dir). Default: examples/calculator"),
    work_dir: Path = typer.Option(Path("runs") / "selftest", help="Build directory"),
    config: Optional[Path] = ConfigOpt,
):
    """Build and run hand-written tests for the bundled sample (checks the toolchain, no LLM)."""
    from importlib import resources

    from .build import Builder, BuildSetupError, run_tests

    cfg = load_config(config)
    project = project or Path(__file__).resolve().parent.parent / "examples" / "calculator"
    if not project.exists():
        typer.secho(f"Sample project not found: {project}. Pass --project.", fg="red", err=True)
        raise typer.Exit(1)
    tests_dir = work_dir / "tests"
    tests_dir.mkdir(parents=True, exist_ok=True)
    test_file = tests_dir / "calculator_selftest.cpp"
    code = resources.files("mast.selftest").joinpath("calculator_selftest.cpp").read_text(encoding="utf-8")
    test_file.write_text(code, encoding="utf-8-sig")
    try:
        builder = Builder(cfg.build, project)
        typer.echo(f"backend: {builder.backend} ({builder.project})")
        builder.prepare(work_dir / "build", [test_file])
        typer.echo("building... (first build also compiles googletest)")
        result = builder.build(work_dir / "build", cfg.run.build_timeout_sec)
    except BuildSetupError as e:
        typer.secho(f"FAILED: {e}", fg="red", err=True)
        raise typer.Exit(1)
    if not result.ok:
        typer.echo(result.log[-5000:])
        typer.secho(f"BUILD FAILED ({result.stage})", fg="red", err=True)
        raise typer.Exit(1)
    run = run_tests(result.exe, work_dir / "build", cfg.run.test_timeout_sec)
    for c in run.cases:
        typer.echo(f"  {c.status:8} {c.full_name}")
    expected_fail = {"CalculatorTest.FactorialOfZeroIsOne"}
    failed = {c.full_name for c in run.cases if c.status != "passed"}
    if failed == expected_fail:
        typer.secho("OK: toolchain works (FactorialOfZeroIsOne fails on purpose: planted bug)", fg="green")
    else:
        typer.secho(f"Unexpected results: {sorted(failed)}", fg="red", err=True)
        raise typer.Exit(1)


if __name__ == "__main__":
    app()
