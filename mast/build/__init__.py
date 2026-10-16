"""Build the generated tests together with the product code and run them."""
from __future__ import annotations

import fnmatch
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from ..analyzer import HEADER_EXTS, SOURCE_EXTS
from ..config import BuildConfig
from . import proc
from .cmake import CMakeSpec, generate_cmakelists
from .gtest_source import GTestSourceError, ensure_gtest
from .results import CaseResult, TestRunResult, merge_results, parse_stdout, parse_xml
from .templates import TEST_MAIN
from .vcxproj import VcxTestSpec, VcxprojInfo, defines_main, generate_test_vcxproj, parse_vcxproj

IS_WINDOWS = os.name == "nt"
_C_EXTS = SOURCE_EXTS + (".c",)


class BuildSetupError(RuntimeError):
    """Configuration problem that no amount of test-code fixing can solve."""


@dataclass
class BuildResult:
    ok: bool
    backend: str
    stage: str  # configure | build
    log: str
    exe: Path | None = None
    seconds: float = 0.0
    commands: list[list[str]] = field(default_factory=list)


def _excluded(rel: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatch(rel, p) or fnmatch.fnmatch(rel, p.removeprefix("**/")) for p in patterns)


def _glob_sources(root: Path, globs: list[str], exclude: list[str]) -> list[Path]:
    found: list[Path] = []
    patterns = globs or ["**/*"]
    for pattern in patterns:
        for p in sorted(root.glob(pattern)):
            if not p.is_file() or p.suffix.lower() not in _C_EXTS:
                continue
            rel = p.relative_to(root).as_posix()
            if _excluded(rel, exclude) or p in found:
                continue
            found.append(p.resolve())
    return found


def _abs_dirs(dirs: list[str], base: Path) -> list[str]:
    out = []
    for d in dirs:
        p = Path(d).expanduser()
        out.append(str(p if p.is_absolute() or "$(" in d else (base / p).resolve()))
    return out


def _dedupe(items: list[str]) -> list[str]:
    seen, out = set(), []
    for i in items:
        key = i.lower() if IS_WINDOWS else i
        if key not in seen:
            seen.add(key)
            out.append(i)
    return out


def find_msbuild(configured: str | None) -> Path:
    if configured:
        p = Path(configured)
        if p.is_file():
            return p
        raise BuildSetupError(f"build.msbuild_path not found: {configured}")
    on_path = shutil.which("msbuild")
    if on_path:
        return Path(on_path)
    pf86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    vswhere = Path(pf86) / "Microsoft Visual Studio" / "Installer" / "vswhere.exe"
    if vswhere.is_file():
        res = proc.run([vswhere, "-latest", "-products", "*", "-requires", "Microsoft.Component.MSBuild",
                        "-find", r"MSBuild\**\Bin\MSBuild.exe"], timeout=60)
        for line in res.output.splitlines():
            if line.strip().lower().endswith("msbuild.exe") and Path(line.strip()).is_file():
                return Path(line.strip())
    raise BuildSetupError(
        "MSBuild not found. Install Visual Studio 2019 / Build Tools (C++ desktop workload) "
        "or set build.msbuild_path."
    )


def resolve_backend(system: str, project: Path) -> tuple[str, Path]:
    """Return (backend, project_path). project_path is a .vcxproj file or the CMake project dir."""
    project = project.resolve()
    if project.is_file():
        if project.suffix.lower() == ".vcxproj":
            if system == "cmake":
                return "cmake", project.parent
            return "vcxproj", project
        if project.name == "CMakeLists.txt":
            return "cmake", project.parent
        raise BuildSetupError(f"--project must be a .vcxproj, a CMakeLists.txt or a directory: {project}")
    if system == "cmake":
        return "cmake", project
    vcxprojs = sorted(project.glob("*.vcxproj"))
    if system == "vcxproj" or (IS_WINDOWS and vcxprojs):
        if len(vcxprojs) != 1:
            raise BuildSetupError(
                f"Found {len(vcxprojs)} .vcxproj files in {project}; pass the one to use with --project")
        return "vcxproj", vcxprojs[0]
    return "cmake", project


class Builder:
    def __init__(self, cfg: BuildConfig, project: Path, header_dirs: list[Path] | None = None):
        self.cfg = cfg
        self.backend, self.project = resolve_backend(cfg.system, project)
        self.project_dir = self.project.parent if self.project.is_file() else self.project
        self.header_dirs = [str(d.resolve()) for d in (header_dirs or [])]
        self.vcx: VcxprojInfo | None = None
        if self.backend == "vcxproj":
            self.vcx = parse_vcxproj(self.project, cfg.configuration, cfg.platform)
        self._configured = False
        self.gtest_root: Path | None = None

    # -- project generation ------------------------------------------------
    def _gtest(self) -> Path:
        if self.gtest_root is None:
            try:
                self.gtest_root = ensure_gtest(self.cfg.gtest_source_dir, Path(self.cfg.cache_dir),
                                               self.cfg.gtest_url, self.cfg.ca_bundle)
            except GTestSourceError as e:
                raise BuildSetupError(str(e)) from e
        return self.gtest_root

    def product_sources(self) -> list[Path]:
        if self.cfg.sources:
            candidates = _glob_sources(self.project_dir, self.cfg.sources, self.cfg.exclude)
        elif self.vcx is not None:
            candidates = [p for p in self.vcx.sources if p.suffix.lower() in _C_EXTS]
        else:
            candidates = _glob_sources(self.project_dir, [], self.cfg.exclude)
        return [p for p in candidates if not defines_main(p)]

    def include_dirs(self) -> list[str]:
        dirs = []
        if self.vcx is not None:
            dirs += self.vcx.include_dirs()
        dirs += _abs_dirs(self.cfg.include_dirs, self.project_dir)
        dirs += self.header_dirs
        if (self.project_dir / "include").is_dir():
            dirs.append(str((self.project_dir / "include").resolve()))
        dirs.append(str(self.project_dir.resolve()))
        return _dedupe(dirs)

    def prepare(self, build_dir: Path, tests: list[Path]) -> Path:
        """Write the test project into build_dir. Returns the project file."""
        build_dir.mkdir(parents=True, exist_ok=True)
        main_file = build_dir / "mast_main.cpp"
        main_file.write_text(TEST_MAIN, encoding="utf-8")
        gtest = self._gtest()
        tests = [t.resolve() for t in tests]
        if self.backend == "vcxproj":
            assert self.vcx is not None
            spec = VcxTestSpec(
                sources=self.product_sources(), tests=tests, gtest_root=gtest, main_file=main_file,
                include_dirs=self.include_dirs(),
                defines=_dedupe(self.vcx.defines() + self.cfg.defines),
                libs=_dedupe(self.vcx.libs() + self.cfg.libs),
                lib_dirs=_dedupe(self.vcx.lib_dirs() + _abs_dirs(self.cfg.lib_dirs, self.project_dir)),
            )
            out = build_dir / "mast_tests.vcxproj"
            out.write_text(generate_test_vcxproj(self.vcx, spec, self.cfg.toolset), encoding="utf-8")
            return out
        target_mode = bool(self.cfg.cmake_target)
        spec = CMakeSpec(
            gtest_root=gtest, tests=tests, main_file=main_file, project_dir=self.project_dir,
            cmake_target=self.cfg.cmake_target,
            sources=None if target_mode else self.product_sources(),
            include_dirs=_abs_dirs(self.cfg.include_dirs, self.project_dir) if target_mode else self.include_dirs(),
            defines=self.cfg.defines, libs=self.cfg.libs,
            lib_dirs=_abs_dirs(self.cfg.lib_dirs, self.project_dir),
        )
        out = build_dir / "CMakeLists.txt"
        out.write_text(generate_cmakelists(spec), encoding="utf-8")
        return out

    # -- build -------------------------------------------------------------
    def build(self, build_dir: Path, timeout: float) -> BuildResult:
        if self.backend == "vcxproj":
            return self._build_msbuild(build_dir, timeout)
        return self._build_cmake(build_dir, timeout)

    def _build_msbuild(self, build_dir: Path, timeout: float) -> BuildResult:
        msbuild = find_msbuild(self.cfg.msbuild_path)
        assert self.vcx is not None
        sln_dir = str((self.vcx.solution_dir or self.project_dir).resolve()).rstrip("\\/") + os.sep
        cmd = [str(msbuild), str(build_dir / "mast_tests.vcxproj"), "/nologo", "/m", "/v:minimal",
               f"/p:Configuration={self.cfg.configuration}", f"/p:Platform={self.cfg.platform}",
               f"/p:SolutionDir={sln_dir}"]
        # VSLANG=1033 makes cl/link print English diagnostics (stable for parsing).
        res = proc.run(cmd, cwd=build_dir, timeout=timeout, env={"VSLANG": "1033"})
        exe = build_dir / "bin" / "mast_tests.exe"
        ok = res.ok and exe.is_file()
        return BuildResult(ok, "vcxproj", "build", res.output, exe if ok else None, res.seconds, [res.args])

    def _build_cmake(self, build_dir: Path, timeout: float) -> BuildResult:
        out_dir = build_dir / "out"
        commands, log, seconds = [], "", 0.0
        if not self._configured or not (out_dir / "CMakeCache.txt").is_file():
            cmd = ["cmake", "-S", str(build_dir), "-B", str(out_dir), f"-DCMAKE_BUILD_TYPE={self.cfg.configuration}"]
            if self.cfg.cmake_generator:
                cmd += ["-G", self.cfg.cmake_generator]
            if IS_WINDOWS and self.cfg.platform and (self.cfg.cmake_generator or "").startswith("Visual Studio"):
                cmd += ["-A", self.cfg.platform]
            cmd += self.cfg.cmake_args
            res = proc.run(cmd, timeout=timeout)
            commands.append(res.args)
            log += res.output
            seconds += res.seconds
            if not res.ok:
                return BuildResult(False, "cmake", "configure", log, None, seconds, commands)
            self._configured = True
        cmd = ["cmake", "--build", str(out_dir), "--config", self.cfg.configuration, "--parallel"]
        res = proc.run(cmd, timeout=timeout)
        commands.append(res.args)
        log += res.output
        seconds += res.seconds
        exe = next((p for p in out_dir.rglob("mast_tests.exe" if IS_WINDOWS else "mast_tests") if p.is_file()), None)
        ok = res.ok and exe is not None
        return BuildResult(ok, "cmake", "build", log, exe if ok else None, seconds, commands)


def run_tests(exe: Path, work_dir: Path, timeout: float, extra_args: list[str] | None = None) -> TestRunResult:
    xml_path = work_dir / "test_results.xml"
    xml_path.unlink(missing_ok=True)
    args = [exe, f"--gtest_output=xml:{xml_path}", "--gtest_color=no", *(extra_args or [])]
    res = proc.run(args, cwd=work_dir, timeout=timeout)
    xml_cases: list[CaseResult] = []
    xml_found = xml_path.is_file()
    if xml_found:
        try:
            xml_cases = parse_xml(xml_path)
        except Exception:
            xml_found = False
    cases = merge_results(xml_cases, parse_stdout(res.output))
    return TestRunResult(exit_code=res.returncode, timed_out=res.timed_out, output=res.output,
                         cases=cases, xml_found=xml_found)


def header_dirs_for(files: list[str], root: Path) -> list[Path]:
    dirs: list[Path] = []
    for f in files:
        p = (root / f).resolve()
        if p.suffix.lower() in HEADER_EXTS and p.parent not in dirs:
            dirs.append(p.parent)
    return dirs


__all__ = [
    "BuildResult",
    "BuildSetupError",
    "Builder",
    "CaseResult",
    "TestRunResult",
    "header_dirs_for",
    "resolve_backend",
    "run_tests",
]
