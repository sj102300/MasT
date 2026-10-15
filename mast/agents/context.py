"""Render analysis results into prompt context for the LLM agents."""
from __future__ import annotations

from pathlib import Path

from ..analyzer import AnalysisResult, FunctionInfo, read_source

MAX_FILE_CHARS = 60_000


def _fence(path: str, text: str) -> str:
    if len(text) > MAX_FILE_CHARS:
        text = text[:MAX_FILE_CHARS] + "\n// ... (truncated)\n"
    return f"### {path}\n```cpp\n{text.rstrip()}\n```\n"


def header_files(analysis: AnalysisResult, functions: list[FunctionInfo]) -> list[str]:
    headers = []
    for fn in functions:
        if fn.decl_file and fn.decl_file not in headers and Path(fn.decl_file).suffix.lower().startswith(".h"):
            headers.append(fn.decl_file)
    return headers


def render_sources(analysis: AnalysisResult, files: list[str]) -> str:
    root = Path(analysis.root)
    parts = []
    for rel in files:
        path = Path(rel) if Path(rel).is_absolute() else root / rel
        if path.is_file():
            parts.append(_fence(rel, read_source(path)))
    return "\n".join(parts)


def render_functions(functions: list[FunctionInfo]) -> str:
    lines = []
    for fn in functions:
        flags = [f for f, on in (("static", fn.is_static), ("const", fn.is_const),
                                 ("virtual", fn.is_virtual), ("template", fn.is_template)) if on]
        lines.append(f"- `{fn.qualified_name}` ({fn.kind}{', ' + ', '.join(flags) if flags else ''})")
        lines.append(f"  signature: `{fn.signature}`")
        lines.append(f"  declared: {fn.decl_file}:{fn.decl_line}"
                     + (f", defined: {fn.def_file}:{fn.def_line}" if fn.def_file else ""))
    return "\n".join(lines)


def source_files_for(analysis: AnalysisResult, functions: list[FunctionInfo]) -> list[str]:
    files: list[str] = []
    for fn in functions:
        for f in (fn.decl_file, fn.def_file):
            if f and f not in files:
                files.append(f)
    return files
