"""Static analysis of C++ sources (no LLM)."""
from __future__ import annotations

from pathlib import Path

from .cpp_parser import CppFileParser, read_source
from .models import AnalysisResult, ClassInfo, FileInfo, FunctionInfo

HEADER_EXTS = (".h", ".hpp", ".hh", ".hxx")
SOURCE_EXTS = (".cpp", ".cc", ".cxx", ".c++")


def _rel(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def find_related_files(target: Path, search_dirs: list[Path]) -> list[Path]:
    """Return target plus its header/source counterpart (same stem)."""
    target = target.resolve()
    exts = HEADER_EXTS if target.suffix.lower() in SOURCE_EXTS else SOURCE_EXTS
    dirs = [target.parent, target.parent.parent / "include", target.parent.parent / "src", *search_dirs]
    found = [target]
    seen = {target}
    for d in dirs:
        for ext in exts:
            cand = (d / (target.stem + ext)).resolve()
            if cand.is_file() and cand not in seen:
                found.append(cand)
                seen.add(cand)
    return found


def _merge(functions: list[FunctionInfo], class_names: set[str]) -> list[FunctionInfo]:
    merged: dict[str, FunctionInfo] = {}
    order: list[str] = []
    for fn in functions:
        existing = merged.get(fn.key)
        if existing is None:
            merged[fn.key] = fn
            order.append(fn.key)
            continue
        decl, defn = (existing, fn) if not existing.body else (fn, existing)
        if decl.body and defn.body:
            continue  # duplicate definition (e.g. same inline in two files): keep first
        combined = decl.model_copy(
            update={"def_file": defn.def_file, "def_line": defn.def_line, "body": defn.body}
        )
        merged[fn.key] = combined

    result = []
    for key in order:
        fn = merged[key]
        owner = fn.qualified_name.rsplit("::", 1)[0] if "::" in fn.qualified_name else ""
        if fn.class_name and owner not in class_names:
            # `ns::func` defined out of line: the qualifier was a namespace, not a class
            fn = fn.model_copy(update={"class_name": "", "kind": "free", "namespace": owner})
        elif fn.class_name and not fn.namespace and "::" in owner:
            fn = fn.model_copy(update={"namespace": owner.rsplit("::", 1)[0]})
        result.append(fn)
    return result


def analyze_files(paths: list[Path], root: Path) -> AnalysisResult:
    files: list[FileInfo] = []
    classes: list[ClassInfo] = []
    functions: list[FunctionInfo] = []
    for path in paths:
        parser = CppFileParser(path, _rel(path, root))
        files.append(parser.parse())
        classes.extend(parser.classes)
        functions.extend(parser.functions)
    class_names = {c.qualified_name for c in classes}
    return AnalysisResult(
        root=root.resolve().as_posix(), files=files, classes=classes, functions=_merge(functions, class_names)
    )


def analyze_target(target: Path, root: Path, search_dirs: list[Path] | None = None) -> AnalysisResult:
    return analyze_files(find_related_files(target, search_dirs or []), root)


__all__ = [
    "AnalysisResult",
    "ClassInfo",
    "FileInfo",
    "FunctionInfo",
    "analyze_files",
    "analyze_target",
    "find_related_files",
    "read_source",
]
