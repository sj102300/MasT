"""Generate a CMake project for the tests (Linux; also works on Windows)."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .templates import CMAKE_HEADER


def _q(p: str | Path) -> str:
    return '"' + str(p).replace("\\", "/").replace('"', '\\"') + '"'


@dataclass
class CMakeSpec:
    gtest_root: Path
    tests: list[Path]
    main_file: Path
    project_dir: Path
    cmake_target: str | None = None
    sources: list[Path] | None = None
    include_dirs: list[str] | None = None
    defines: list[str] | None = None
    libs: list[str] | None = None
    lib_dirs: list[str] | None = None


def generate_cmakelists(spec: CMakeSpec) -> str:
    out = CMAKE_HEADER.format(gtest_root=str(spec.gtest_root).replace("\\", "/"))
    if spec.cmake_target:
        out += f'add_subdirectory({_q(spec.project_dir)} "${{CMAKE_BINARY_DIR}}/product" EXCLUDE_FROM_ALL)\n'
    files = [*spec.tests, spec.main_file, *(spec.sources or [])]
    out += "\nadd_executable(mast_tests\n" + "".join(f"    {_q(f)}\n" for f in files) + ")\n"
    if spec.include_dirs:
        out += "target_include_directories(mast_tests PRIVATE\n" + "".join(
            f"    {_q(d)}\n" for d in spec.include_dirs) + ")\n"
    if spec.defines:
        out += "target_compile_definitions(mast_tests PRIVATE\n" + "".join(
            f"    {_q(d)}\n" for d in spec.defines) + ")\n"
    if spec.lib_dirs:
        out += "target_link_directories(mast_tests PRIVATE\n" + "".join(
            f"    {_q(d)}\n" for d in spec.lib_dirs) + ")\n"
    libs = ([spec.cmake_target] if spec.cmake_target else []) + list(spec.libs or []) + ["GTest::gtest"]
    out += "target_link_libraries(mast_tests PRIVATE\n" + "".join(f"    {lib}\n" for lib in libs) + ")\n"
    out += "if(MSVC)\n    target_compile_options(mast_tests PRIVATE /bigobj)\nendif()\n"
    return out
