"""Verifier: classify a build + test run into what should happen next (no LLM)."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from ..build import BuildResult, CaseResult, TestRunResult
from .diagnostics import Diagnostic, Locator, context_lines, parse_diagnostics

VerdictKind = Literal[
    "pass",              # every test passed
    "build_error_test",  # compile errors inside generated test code -> Fixer
    "build_error_env",   # include paths, missing sources/libs, toolset... -> user must fix config
    "test_failures",     # built and ran; some tests failed/crashed/timed out -> Fixer judges
    "run_error",         # binary failed before any test ran
    "no_tests",          # built, but no test was registered
]

_ENV_HINTS = [
    ("MSB8020", "Platform Toolset을 찾을 수 없음 → config.yaml build.toolset 을 설치된 버전(v142/v143)으로 지정"),
    ("MSB8036", "Windows SDK 버전 없음 → Visual Studio Installer에서 Windows 10/11 SDK 설치"),
    ("C1083", "헤더를 찾을 수 없음 → build.include_dirs 에 경로 추가"),
    ("LNK2019", "링크 실패(정의 없음) → 해당 함수가 있는 소스를 build.sources 에, 라이브러리를 build.libs 에 추가"),
    ("LNK2001", "링크 실패(정의 없음) → build.sources / build.libs 확인"),
    ("undefined reference", "링크 실패(정의 없음) → build.sources / build.libs 확인 (CMake면 build.cmake_target 사용 검토)"),
    ("cannot find -l", "라이브러리를 찾을 수 없음 → build.lib_dirs 확인"),
    ("CMake Error", "CMake 구성 실패 → 로그 확인, build.cmake_target / cmake_args 확인"),
]


class Verdict(BaseModel):
    kind: VerdictKind
    summary: str
    diagnostics: list[Diagnostic] = Field(default_factory=list)
    failures: list[CaseResult] = Field(default_factory=list)
    passed: int = 0
    total: int = 0
    hints: list[str] = Field(default_factory=list)
    log_excerpt: str = ""


def _hints(diags: list[Diagnostic], log: str) -> list[str]:
    out = []
    for key, hint in _ENV_HINTS:
        if any(key in (d.code + " " + d.message + " " + d.raw) for d in diags) or (not diags and key in log):
            out.append(hint)
    return out


def _excerpt(diags: list[Diagnostic], log: str, limit: int = 40) -> str:
    if not diags:
        return "\n".join(log.strip().splitlines()[-limit:])
    return "\n".join(context_lines(log, d) for d in diags[:limit])


def verify(build: BuildResult, run: TestRunResult | None, locator: Locator) -> Verdict:
    if not build.ok:
        diags = parse_diagnostics(build.log, locator)
        test_errors = [d for d in diags if d.location == "test" and d.kind == "compile"]
        if test_errors:
            return Verdict(
                kind="build_error_test",
                summary=f"테스트 코드 컴파일 에러 {len(test_errors)}건",
                diagnostics=test_errors,
                log_excerpt=_excerpt(test_errors, build.log),
            )
        return Verdict(
            kind="build_error_env",
            summary=f"빌드 환경/설정 문제 ({build.stage} 단계, 에러 {len(diags)}건)",
            diagnostics=diags,
            hints=_hints(diags, build.log),
            log_excerpt=_excerpt(diags, build.log),
        )

    assert run is not None
    total = len(run.cases)
    passed = run.count("passed") + run.count("skipped")
    if total == 0:
        if run.exit_code not in (0, 1) or run.timed_out:
            return Verdict(kind="run_error", summary=f"테스트 실행 실패 (exit code {run.exit_code})",
                           log_excerpt="\n".join(run.output.splitlines()[-40:]))
        return Verdict(kind="no_tests", summary="등록된 테스트가 없음", log_excerpt=run.output[-2000:])

    failures = [c for c in run.cases if c.status in ("failed", "crashed")]
    if run.timed_out:
        for c in failures:
            if c.status == "crashed":
                c.message = (c.message + "\n[mast] test run timed out while this test was running").strip()
    if not failures and not run.timed_out:
        return Verdict(kind="pass", summary=f"전체 통과 {passed}/{total}", passed=passed, total=total)
    not_run = total - passed - len(failures)
    summary = f"실패 {len(failures)}건 / 통과 {passed}건 / 전체 {total}건"
    if not_run:
        summary += f" (미실행 {not_run}건)"
    return Verdict(kind="test_failures", summary=summary, failures=failures, passed=passed, total=total)


__all__ = ["Diagnostic", "Locator", "Verdict", "parse_diagnostics", "verify"]
