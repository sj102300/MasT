import json

from mast.report import render_report


def test_report_env_error_and_unclear(tmp_path):
    (tmp_path / "plan.json").write_text(json.dumps({"test_cases": [
        {"id": "TC001", "function": "ns::f", "suite": "S", "name": "A", "category": "normal",
         "description": "설명 | 파이프", "input": "", "expected": "1", "notes": ""}]}), encoding="utf-8")
    (tmp_path / "result.json").write_text(json.dumps({
        "outcome": "env_error", "message": "빌드 환경/설정 문제", "backend": "vcxproj",
        "judgments": {"S.A": {"test": "S.A", "verdict": "unclear", "reason": "명세 없음"}},
        "cases": [],
        "iterations": [{"index": 0, "action": "write", "build_seconds": 1.5, "test_file": "x",
                        "verdict": {"kind": "build_error_env", "summary": "빌드 환경/설정 문제",
                                    "hints": ["build.include_dirs 에 경로 추가"], "log_excerpt": "fatal error C1083"}}],
    }), encoding="utf-8")
    md = render_report(tmp_path)
    assert "🛠️ 빌드 환경/설정 문제" in md
    assert "build.include_dirs 에 경로 추가" in md and "fatal error C1083" in md
    assert "`S.A` (판단 필요): 명세 없음" in md
    assert "설명 \\| 파이프" in md  # table cell escaped
    assert "| 0 | 최초 생성 |" in md
