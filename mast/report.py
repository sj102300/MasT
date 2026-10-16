"""Reporter: render a run directory into a Markdown report (Korean)."""
from __future__ import annotations

import json
from pathlib import Path

OUTCOME_LABEL = {
    "pass": "✅ 전체 통과",
    "product_bugs": "🐞 제품 코드 버그 의심",
    "unresolved": "⚠️ 미해결 (확인 필요)",
    "env_error": "🛠️ 빌드 환경/설정 문제",
    "generated_only": "📝 코드 생성만 수행",
    "error": "❌ 실행 오류",
}
STATUS_LABEL = {
    "passed": "✅ 통과",
    "failed": "❌ 실패",
    "crashed": "💥 크래시",
    "skipped": "⏭️ 건너뜀",
    "not_run": "— 미실행",
}
ACTION_LABEL = {"write": "최초 생성", "fix_build": "컴파일 에러 수정", "fix_tests": "테스트 오류 수정"}
VERDICT_LABEL = {"test_bug": "테스트 오류", "product_bug": "제품 버그", "unclear": "판단 필요"}


def _load(run_dir: Path, name: str):
    path = run_dir / name
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _cell(text: str, limit: int = 120) -> str:
    text = " ".join(str(text or "").split()).replace("|", "\\|")
    return text if len(text) <= limit else text[: limit - 1] + "…"


def render_report(run_dir: Path) -> str:
    plan = _load(run_dir, "plan.json") or {"test_cases": []}
    result = _load(run_dir, "result.json") or {}
    usage = _load(run_dir, "usage.json") or {}
    analysis = _load(run_dir, "analysis.json") or {}
    files = [f["path"] for f in analysis.get("files", [])]
    target = files[0] if files else run_dir.name

    outcome = result.get("outcome", "error")
    iterations = result.get("iterations", [])
    judgments: dict = result.get("judgments", {})
    cases = {f'{c["suite"]}.{c["name"]}': c for c in result.get("cases", [])}

    out = [f"# MasT 테스트 리포트 — `{target}`", ""]
    out.append(f"- **결과**: {OUTCOME_LABEL.get(outcome, outcome)} — {result.get('message', '')}")
    if result.get("backend"):
        out.append(f"- **빌드**: {result['backend']}, 반복 {len(iterations)}회")
    if result.get("total"):
        out.append(f"- **테스트**: 통과 {result.get('passed', 0)} / 전체 {result['total']}")
    out.append(f"- **테스트 케이스 설계**: {len(plan['test_cases'])}건")
    if usage:
        out.append(f"- **LLM 사용량**: 호출 {usage.get('calls', 0)}회, 입력 {usage.get('input_tokens', 0):,} / "
                   f"출력 {usage.get('output_tokens', 0):,} 토큰")
    out.append("")

    bugs = [j for j in judgments.values() if j["verdict"] == "product_bug"]
    if bugs:
        out += ["## 🐞 제품 코드 버그 의심", "",
                "테스트의 기대값은 함수 주석/이름/시그니처(계약)를 기준으로 한다. 제품 코드는 수정하지 않았다.", ""]
        for j in bugs:
            fix = j.get("product_fix") or {}
            out.append(f"### `{j['test']}`")
            out.append(f"- 원인: {j.get('reason', '')}")
            if fix.get("file"):
                loc = f"{fix['file']}:{fix['line']}" if fix.get("line") else fix["file"]
                out.append(f"- 위치: `{loc}`")
            if fix.get("description"):
                out.append(f"- 수정 제안: {fix['description']}")
            if fix.get("patch"):
                out += ["", "```diff" if fix["patch"].lstrip().startswith(("---", "@@", "-", "+")) else "```cpp",
                        fix["patch"].rstrip(), "```"]
            failure = cases.get(j["test"], {}).get("message")
            if failure:
                out += ["", "<details><summary>실패 출력</summary>", "", "```", failure.strip()[-2000:], "```",
                        "", "</details>"]
            out.append("")

    unclear = [j for j in judgments.values() if j["verdict"] != "product_bug"]
    if unclear:
        out += ["## ⚠️ 판단 필요 / 미해결 실패", ""]
        for j in unclear:
            out.append(f"- `{j['test']}` ({VERDICT_LABEL.get(j['verdict'], j['verdict'])}): {j.get('reason', '')}")
        out.append("")

    last = iterations[-1]["verdict"] if iterations else None
    if last and last["kind"] in ("build_error_env", "build_error_test", "run_error"):
        out += ["## 🛠️ 빌드/실행 문제", "", f"{last['summary']}", ""]
        for h in last.get("hints", []):
            out.append(f"- {h}")
        if last.get("log_excerpt"):
            out += ["", "```", last["log_excerpt"].strip()[-4000:], "```"]
        out.append("")

    out += ["## 테스트 케이스", "", "| ID | 테스트 | 함수 | 분류 | 설명 | 기대값 | 결과 |",
            "|---|---|---|---|---|---|---|"]
    for tc in plan["test_cases"]:
        full = f'{tc["suite"]}.{tc["name"]}'
        case = cases.get(full)
        if case:
            status = STATUS_LABEL.get(case["status"], case["status"])
            if full in judgments:
                status += f" ({VERDICT_LABEL.get(judgments[full]['verdict'], '')})"
        else:
            status = "— (결과 없음)" if cases else "—"
        out.append(f"| {tc['id']} | `{_cell(full, 60)}` | `{_cell(tc['function'].split('::')[-1], 40)}` | "
                   f"{tc['category']} | {_cell(tc['description'])} | {_cell(tc['expected'], 60)} | {status} |")
    extra = [name for name in cases if name not in {f'{t["suite"]}.{t["name"]}' for t in plan["test_cases"]}]
    for name in extra:
        out.append(f"| - | `{name}` | | | (계획에 없는 테스트) | | {STATUS_LABEL.get(cases[name]['status'], '')} |")
    out.append("")

    if iterations:
        out += ["## 진행 이력", "", "| # | 테스트 코드 | 결과 | 빌드(초) |", "|---|---|---|---|"]
        for it in iterations:
            out.append(f"| {it['index']} | {ACTION_LABEL.get(it['action'], it['action'])} | "
                       f"{_cell(it['verdict']['summary'])} | {it.get('build_seconds', 0):.1f} |")
        out.append("")

    tests = sorted((run_dir / "tests").glob("*")) if (run_dir / "tests").is_dir() else []
    out += ["## 파일", ""]
    out += [f"- 테스트 코드: `{t.relative_to(run_dir).as_posix()}`" for t in tests]
    out += ["- 수정 이력: `history/`", "- 빌드 로그: `build.log`", "- 테스트 출력: `test_output.log`",
            "- LLM 요청/응답: `llm_calls.jsonl`", ""]
    return "\n".join(out)


def write_report(run_dir: Path) -> Path:
    path = run_dir / "report.md"
    path.write_text(render_report(run_dir), encoding="utf-8")
    return path
