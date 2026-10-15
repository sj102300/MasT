"""MasT web UI (Streamlit). Launch with `mast ui`."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

from mast.analyzer import HEADER_EXTS, SOURCE_EXTS, FunctionInfo, analyze_target
from mast.build import BuildSetupError
from mast.config import AppConfig, load_config
from mast.llm import LLMError
from mast.orchestrator import Pipeline, RunRequest
from mast.report import OUTCOME_LABEL, STATUS_LABEL, VERDICT_LABEL, write_report

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SKIP_DIRS = {"build", "out", "runs", ".git", ".vs", "x64", "Debug", "Release", "third_party", "node_modules"}
STAGES = ["analyze", "plan", "write", "build", "test", "verify", "fix", "done"]
STAGE_LABEL = {"analyze": "분석", "plan": "TC 설계", "write": "코드 생성", "build": "빌드", "test": "실행",
               "verify": "검증", "fix": "수정", "done": "완료"}


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=None)
    known, _ = parser.parse_known_args(sys.argv[1:])
    return known


# -- sidebar: configuration ---------------------------------------------------
def sidebar_config() -> AppConfig:
    st.sidebar.title("MasT")
    st.sidebar.caption("C++ 단위테스트 자동 생성")
    default_cfg = _args().config or ("config.yaml" if Path("config.yaml").is_file() else "")
    cfg_path = st.sidebar.text_input("설정 파일", value=default_cfg, placeholder="config.yaml (없으면 기본값)")
    try:
        cfg = load_config(cfg_path) if cfg_path else AppConfig()
    except (OSError, ValueError) as e:
        st.sidebar.error(f"설정 파일 오류: {e}")
        cfg = AppConfig()

    with st.sidebar.expander("LLM", expanded=False):
        providers = ["anthropic", "openai_compat"]
        cfg.llm.provider = st.selectbox("provider", providers, index=providers.index(cfg.llm.provider))
        cfg.llm.model = st.text_input("model", cfg.llm.model)
        if cfg.llm.provider == "openai_compat":
            cfg.llm.base_url = st.text_input("base_url", cfg.llm.base_url or "") or None
        cfg.llm.api_key_env = st.text_input("API 키 환경변수", cfg.llm.api_key_env)
        if os.environ.get(cfg.llm.api_key_env):
            st.success(f"${cfg.llm.api_key_env} 설정됨")
        else:
            st.warning(f"${cfg.llm.api_key_env} 미설정")

    with st.sidebar.expander("빌드", expanded=False):
        systems = ["auto", "vcxproj", "cmake"]
        cfg.build.system = st.selectbox("빌드 방식", systems, index=systems.index(cfg.build.system))
        cfg.build.configuration = st.text_input("Configuration", cfg.build.configuration)
        cfg.build.platform = st.text_input("Platform", cfg.build.platform)
        cfg.build.toolset = st.text_input("PlatformToolset 덮어쓰기", cfg.build.toolset or "",
                                          placeholder="비우면 원본 값 (예: v142)") or None
        cfg.run.max_fix_iterations = st.number_input("최대 수정 횟수", 0, 10, cfg.run.max_fix_iterations)
    cfg.run.output_dir = st.sidebar.text_input("결과 폴더", cfg.run.output_dir)
    return cfg


# -- new run --------------------------------------------------------------------
def list_sources(root: Path) -> list[str]:
    exts = SOURCE_EXTS + HEADER_EXTS
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
        for name in filenames:
            if Path(name).suffix.lower() in exts:
                out.append(Path(dirpath, name).relative_to(root).as_posix())
            if len(out) > 5000:
                return sorted(out)
    return sorted(out)


@st.cache_data(show_spinner=False)
def cached_analysis(target: str, root: str, mtime: float):
    return analyze_target(Path(target), Path(root)).model_dump()


def new_run(cfg: AppConfig) -> None:
    default_project = REPO_ROOT / "examples" / "calculator"
    if os.name == "nt" and (default_project / "calculator.vcxproj").is_file():
        default_project = default_project / "calculator.vcxproj"
    project_str = st.text_input("프로젝트 (.vcxproj 파일 또는 CMake 프로젝트 폴더)", str(default_project))
    project = Path(project_str.strip().strip('"')) if project_str else None
    if not project or not project.exists():
        st.info("프로젝트 경로를 입력하세요.")
        return
    root = project if project.is_dir() else project.parent

    sources = list_sources(root)
    cpp_first = sorted(sources, key=lambda s: (Path(s).suffix.lower() not in SOURCE_EXTS, s))
    if not cpp_first:
        st.warning("C++ 소스가 없습니다.")
        return
    target_rel = st.selectbox("테스트 대상 파일", cpp_first)
    target = (root / target_rel).resolve()

    data = cached_analysis(str(target), str(root), target.stat().st_mtime)
    testable = [f for f in data["functions"] if _testable(f)]
    st.caption("분석 파일: " + ", ".join(f["path"] for f in data["files"]))
    if not testable:
        st.warning("테스트 가능한 public 함수가 없습니다.")
        return
    names = [f["qualified_name"] for f in testable]
    chosen = st.multiselect(f"테스트할 함수 ({len(names)}개 중)", names, default=names)
    do_build = st.checkbox("빌드·실행·수정까지 진행", value=True)

    if st.button("테스트 생성 시작", type="primary", disabled=not chosen):
        run_pipeline(cfg, RunRequest(project_root=root, target=target, functions=chosen,
                                     project=project.resolve(), build=do_build))
    if st.session_state.get("last_run"):
        st.divider()
        show_run(Path(st.session_state["last_run"]), "new")


def _testable(f: dict) -> bool:
    return FunctionInfo(**f).is_testable


def run_pipeline(cfg: AppConfig, req: RunRequest) -> None:
    progress = st.progress(0.0, text="시작")
    with st.status("실행 중...", expanded=True) as status:
        def on_event(e):
            idx = STAGES.index(e.stage) if e.stage in STAGES else 0
            progress.progress((idx + 1) / len(STAGES), text=f"{STAGE_LABEL.get(e.stage, e.stage)}: {e.message}")
            st.write(f"**{STAGE_LABEL.get(e.stage, e.stage)}** — {e.message}")

        try:
            state = Pipeline(cfg, on_event).run(req)
        except (LLMError, ValueError, BuildSetupError) as e:
            status.update(label="실패", state="error")
            st.error(str(e))
            return
        res = state.result
        ok = res.outcome in ("pass", "product_bugs", "generated_only")
        status.update(label=OUTCOME_LABEL.get(res.outcome, res.outcome), state="complete" if ok else "error",
                      expanded=False)
    st.session_state["last_run"] = str(state.run_dir)


# -- results ------------------------------------------------------------------
def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig", errors="replace") if path.is_file() else ""


def _demote_headings(md: str) -> str:
    """The report's H1/H2 are too large inside a tab; shift every heading down two levels."""
    out, fence = [], False
    for line in md.splitlines():
        if line.startswith("```"):
            fence = not fence
        if not fence and line.startswith("#"):
            line = "##" + line
        out.append(line)
    return "\n".join(out)


def show_run(run_dir: Path, ctx: str) -> None:
    result = json.loads(_read(run_dir / "result.json") or "{}")
    plan = json.loads(_read(run_dir / "plan.json") or '{"test_cases": []}')
    st.subheader(f"결과: {run_dir.name}")
    outcome = result.get("outcome", "")
    label = OUTCOME_LABEL.get(outcome, outcome or "-")
    if outcome == "pass":
        st.success(label)
    elif outcome in ("product_bugs", "unresolved", "generated_only"):
        st.warning(label)
    else:
        st.error(label)
    c2, c3, c4 = st.columns(3)
    c2.metric("통과 / 전체", f"{result.get('passed', 0)} / {result.get('total', 0)}")
    c3.metric("반복", len(result.get("iterations", [])))
    c4.metric("TC 설계", len(plan["test_cases"]))
    if result.get("message"):
        st.caption(result["message"])

    if not (run_dir / "report.md").is_file() and (run_dir / "plan.json").is_file():
        write_report(run_dir)
    tabs = st.tabs(["리포트", "테스트 코드", "TC 계획", "빌드 로그", "테스트 출력", "LLM 호출"])
    with tabs[0]:
        st.markdown(_demote_headings(_read(run_dir / "report.md")) or "리포트 없음")
    with tabs[1]:
        tests = sorted((run_dir / "tests").glob("*")) if (run_dir / "tests").is_dir() else []
        for t in tests:
            code = _read(t)
            st.download_button(f"{t.name} 다운로드", code, file_name=t.name, key=f"{ctx}-dl-{t}")
            st.code(code, language="cpp", line_numbers=True)
        history = sorted((run_dir / "history").glob("*")) if (run_dir / "history").is_dir() else []
        if len(history) > 1:
            with st.expander(f"수정 이력 ({len(history)}개 버전)"):
                version = st.selectbox("버전", [h.name for h in history], key=f"{ctx}-hist-{run_dir}")
                st.code(_read(run_dir / "history" / version), language="cpp", line_numbers=True)
    with tabs[2]:
        cases = {f'{c["suite"]}.{c["name"]}': c for c in result.get("cases", [])}
        judgments = result.get("judgments", {})
        rows = []
        for tc in plan["test_cases"]:
            full = f'{tc["suite"]}.{tc["name"]}'
            status = STATUS_LABEL.get(cases.get(full, {}).get("status", ""), "—")
            if full in judgments:
                status += f" ({VERDICT_LABEL.get(judgments[full]['verdict'], '')})"
            rows.append({"ID": tc["id"], "테스트": full, "결과": status, "함수": tc["function"],
                         "분류": tc["category"], "설명": tc["description"], "입력": tc["input"],
                         "기대값": tc["expected"], "비고": tc.get("notes", "")})
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    with tabs[3]:
        st.code(_read(run_dir / "build.log")[-50000:] or "(없음)", language="text")
    with tabs[4]:
        st.code(_read(run_dir / "test_output.log")[-50000:] or "(없음)", language="text")
    with tabs[5]:
        calls_path = run_dir / "llm_calls.jsonl"
        for i, line in enumerate(_read(calls_path).splitlines(), 1):
            call = json.loads(line)
            title = f"{i}. {call['agent']} — {call['seconds']}s, in {call['input_tokens']} / out {call['output_tokens']}"
            if call.get("error"):
                title += " ⚠️ error"
            with st.expander(title):
                for m in call["messages"]:
                    st.markdown(f"**{m['role']}**")
                    st.code(m["content"][-20000:], language="markdown")
                st.markdown("**response**")
                st.code((call.get("response") or call.get("error") or "")[-20000:], language="markdown")


def history_tab(cfg: AppConfig) -> None:
    base = Path(cfg.run.output_dir)
    runs = sorted([d for d in base.glob("*") if (d / "plan.json").is_file()], reverse=True) if base.is_dir() else []
    if not runs:
        st.info(f"{base} 에 실행 기록이 없습니다.")
        return
    labels = {}
    for d in runs:
        res = json.loads(_read(d / "result.json") or "{}")
        labels[d.name] = f"{d.name}  —  {OUTCOME_LABEL.get(res.get('outcome', ''), '진행 중/오류')}"
    name = st.selectbox("실행", list(labels), format_func=labels.get)
    show_run(base / name, "history")


def main() -> None:
    st.set_page_config(page_title="MasT", page_icon="🧪", layout="wide")
    cfg = sidebar_config()
    tab_new, tab_hist = st.tabs(["새 실행", "실행 기록"])
    with tab_new:
        new_run(cfg)
    with tab_hist:
        history_tab(cfg)


main()
