# MasT

C++ 프로젝트의 googletest 단위테스트를 자동 생성·빌드·검증하는 멀티 에이전트 시스템. 설계는 [PLAN.md](PLAN.md) 참고.

## 요구사항
- Python 3.11+
- Windows: Visual Studio 2019 (또는 Build Tools, "C++를 사용한 데스크톱 개발")
- Linux: CMake 3.20+, gcc (C++17)

## 설치

Windows (PowerShell):
```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
.\.venv\Scripts\Activate.ps1
$env:ANTHROPIC_API_KEY = "sk-..."
mast check-llm
```

Linux:
```bash
./scripts/setup.sh
source .venv/bin/activate
export ANTHROPIC_API_KEY=sk-...
mast check-llm
```

## LLM 설정
`config.yaml`의 `llm.provider`로 선택한다.
- `anthropic`: Claude API
- `openai_compat`: OpenAI 호환 API (사내 LLM). `base_url`, `model`, `api_key_env` 지정

사내 인증서는 `ca_bundle`, 프록시는 `proxy`로 지정한다. 에이전트별 모델은 `agents.<이름>`으로 덮어쓴다. 예시는 `config.example.yaml`.

## 테스트
```bash
pytest
```

## 사용법
```bash
# 툴체인 확인 (LLM 호출 없음): 샘플 프로젝트에 손으로 쓴 테스트를 빌드·실행
mast selftest                                                    # Windows: vcxproj/msbuild, Linux: CMake
mast selftest --project examples\calculator\calculator.vcxproj   # Windows에서 명시

# 함수 목록 확인 (LLM 호출 없음)
mast analyze examples/calculator/src/calculator.cpp --root examples/calculator

# 테스트 생성 (현재: 분석 → TC 설계 → 코드 생성)
mast generate examples/calculator/src/calculator.cpp --root examples/calculator
```
결과는 `runs/<시각>-<파일명>/`에 저장된다: `analysis.json`, `plan.json`, `tests/*_test.cpp`, `llm_calls.jsonl`(LLM 요청/응답 기록), `usage.json`.

프롬프트는 `mast/prompts/*.md`에서 수정한다.

## 빌드 방식
- **Windows**: 제품 `.vcxproj`에서 include 경로, 전처리기 정의, 런타임 라이브러리, 속성 시트(.props), 프로젝트 참조를 읽어 `mast_tests.vcxproj`를 따로 생성하고 msbuild로 빌드한다. 원본 sln/vcxproj는 건드리지 않는다. googletest는 같은 프로젝트에서 소스로 함께 컴파일된다.
- **Linux**: 테스트용 `CMakeLists.txt`를 생성한다. 기본은 제품 소스를 직접 컴파일, `build.cmake_target`을 지정하면 제품 CMake 타깃에 링크한다.
- googletest 소스는 처음 한 번 `~/.mast/cache`에 받는다(zip → 실패 시 git clone). 사내망에서 막히면 직접 받아 `build.gtest_source_dir`에 지정.
- 자동으로 못 읽는 설정은 `config.yaml`의 `build.include_dirs / defines / libs / sources`로 보충한다.
