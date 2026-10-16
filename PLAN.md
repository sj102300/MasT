# MasT — C++ 단위테스트 자동 생성 멀티 에이전트 시스템 계획

## 1. 목표 (1단계 범위)
C++ 프로젝트를 입력받아
1. 테스트케이스 자동 생성 (googletest)
2. 테스트 빌드·실행
3. 결과 검증
4. 실패 시 수정방안 제시 (테스트 코드 오류는 자동 수정, 제품 코드 의심은 리포트만)

제외(추후): gmock 모킹, 커버리지 측정, 사내 nsfwtest 프레임워크.

## 2. 확정 사항
| 항목 | 결정 |
|---|---|
| 구현 언어 | Python 3.11+ |
| 대상 | C++17 |
| 테스트 프레임워크 | googletest 1.17 (프레임워크 어댑터로 추상화 → nsfwtest 추가 가능) |
| LLM | Claude API / 사내 LLM(OpenAI 호환). `config.yaml`로 선택 |
| Windows 빌드 | VS2019(MSVC v142). 기존 vcxproj를 읽어 테스트용 vcxproj 자동 생성 → msbuild |
| Linux 빌드 | Rocky Linux 10, CMake + gcc |
| UI | CLI + 웹 UI(Streamlit) |

## 3. 아키텍처

```
          ┌──────────────┐
 입력 ──▶ │  Analyzer    │  (LLM X) 소스 파싱 → 함수/클래스 목록, 시그니처, include
          └──────┬───────┘
                 ▼
          ┌──────────────┐
          │  Planner     │  (LLM) 함수별 TC 시나리오: 정상/경계/예외
          └──────┬───────┘
                 ▼
          ┌──────────────┐
          │  Writer      │  (LLM) gtest 코드 생성
          └──────┬───────┘
                 ▼
          ┌──────────────┐
     ┌──▶ │  Builder     │  (LLM X) 테스트 프로젝트 생성 + 빌드 + 실행(--gtest_output=xml)
     │    └──────┬───────┘
     │           ▼
     │    ┌──────────────┐
     │    │  Verifier    │  (LLM X+O) 빌드 로그/XML 파싱 → 성공/컴파일에러/실패 분류
     │    └──────┬───────┘
     │           ▼  실패 시
     │    ┌──────────────┐
     └─── │  Fixer       │  (LLM) 원인 판정
          └──────────────┘    - 테스트 코드 오류 → 수정 후 재빌드 (최대 N회)
                              - 제품 코드 버그 의심 → 수정 안 함, 수정방안 리포트
                 ▼
          ┌──────────────┐
          │  Reporter    │  결과 리포트(Markdown/JSON): TC 목록, 통과/실패, 수정방안
          └──────────────┘
```

- 오케스트레이터: 프레임워크 없이 Python 상태머신(단계·재시도 횟수·이력 관리). 단계별 산출물을 `runs/<timestamp>/`에 저장해 재실행/디버깅 가능.
- 에이전트 간 데이터: JSON 스키마(pydantic)로 고정. LLM 응답도 JSON으로 받아 검증.
- 프롬프트: `prompts/*.md`로 분리.

## 4. 주요 모듈

### 4.1 LLM 어댑터 (`mast/llm/`)
```yaml
# config.yaml
llm:
  provider: anthropic          # anthropic | openai_compat
  model: claude-sonnet-5-5
  api_key_env: ANTHROPIC_API_KEY   # 키는 환경변수로만
  base_url: null               # openai_compat일 때 사내 URL
  max_tokens: 8192
  temperature: 0.2
  timeout_sec: 120
  verify_ssl: true             # 사내 인증서 경로 지정 가능(ca_bundle)
```
- `LLMClient.chat(system, messages) -> str` 공통 인터페이스
- 구현: `AnthropicClient`(anthropic SDK), `OpenAICompatClient`(openai SDK + base_url)
- 에이전트별 모델 오버라이드 허용(예: Fixer만 상위 모델)
- 사내망 프록시/CA 설정 지원

### 4.2 Analyzer (`mast/analyzer/`)
- tree-sitter-cpp로 헤더/소스 파싱: namespace, class, public 메서드, 자유 함수, 시그니처, 주석
- 테스트 대상 선택: 파일/클래스/함수 단위 필터
- 컨텍스트 축약: 대상 함수 본문 + 관련 헤더만 LLM에 전달(토큰 절약)

### 4.3 프레임워크 어댑터 (`mast/frameworks/`)
- `TestFramework` 인터페이스: 코드 생성 규칙(프롬프트 조각), 결과 파서, 빌드 시 필요한 소스/라이브러리
- `GTestFramework` 구현. 추후 `NsfwTestFramework` 추가

### 4.4 Builder (`mast/build/`)
**Windows (VS2019)**
- 대상 `.vcxproj`(XML) 파싱: `Configuration|Platform`별 `AdditionalIncludeDirectories`, `PreprocessorDefinitions`, `LanguageStandard`, `RuntimeLibrary`, `ClCompile` 소스 목록, 매크로(`$(SolutionDir)` 등) 치환
- 테스트용 `mast_tests.vcxproj` 생성: 대상 소스(진입점 `main` 포함 파일 제외) + 생성된 테스트 + gtest 소스(`gtest-all.cc`, `gtest_main.cc` 직접 컴파일 → 별도 gtest 빌드 불필요)
- 기존 `.sln`/`.vcxproj`는 수정하지 않음
- `vswhere.exe`로 msbuild 경로 자동 탐색, `msbuild mast_tests.vcxproj /p:Configuration=Debug /p:Platform=x64`

**Linux (Rocky 10)**
- 대상 CMake 프로젝트의 라이브러리 타깃에 링크하는 테스트용 `CMakeLists.txt` 생성, gtest는 FetchContent
- 라이브러리 타깃이 없으면 소스 직접 포함 방식으로 fallback

**공통**
- gtest 소스는 고정 버전 zip을 1회 다운로드해 `~/.mast/cache`에 보관(사내망 대비 로컬 경로 지정 옵션)
- 실행: `--gtest_output=xml:result.xml`, 타임아웃 적용

### 4.5 Verifier / Fixer
- 분류: `BUILD_ERROR`(테스트 코드) / `BUILD_ERROR`(환경: include·링크) / `TEST_FAIL` / `CRASH` / `TIMEOUT` / `PASS`
- 컴파일 에러는 MSVC(`error C2065`)·gcc 형식 모두 파싱해 파일·라인·메시지 추출
- Fixer 판정 기준: 기대값이 명세/주석/함수명과 맞는지 LLM이 근거와 함께 판단
  - 테스트 오류 → 해당 TC만 수정 후 재빌드
  - 제품 버그 의심 → 해당 TC를 `DISABLED_` 처리하지 않고 그대로 두고 리포트에 원인·수정 제안(diff) 기록
- 루프 제한: 기본 3회, 같은 에러 반복 시 조기 종료

### 4.6 인터페이스
- CLI (typer):
  ```
  mast generate --project C:\work\foo\foo.vcxproj --target src\calc.cpp
  mast generate --project ./foo --build cmake --target src/calc.cpp
  mast report runs/2026xxxx
  ```
- 웹 UI (Streamlit): 프로젝트/대상 선택 → 진행 단계 실시간 표시 → 생성 코드, 빌드 로그, 테스트 결과, 수정방안 탭

## 5. 레포 구조
```
MasT/
├─ mast/
│  ├─ llm/          # anthropic, openai_compat
│  ├─ analyzer/     # tree-sitter 파싱
│  ├─ agents/       # planner, writer, fixer
│  ├─ frameworks/   # gtest (nsfwtest 예정)
│  ├─ build/        # vcxproj, cmake, runner, log parser
│  ├─ verify/       # 빌드 로그 진단 파싱, 결과 분류
│  ├─ webui/app.py  # Streamlit (mast ui)
│  ├─ report.py
│  ├─ orchestrator.py
│  └─ cli.py
├─ prompts/
├─ examples/calculator/   # 샘플 C++17 프로젝트 (sln/vcxproj + CMakeLists 둘 다)
├─ tests/                 # MasT 자체 pytest (LLM은 mock)
├─ scripts/setup.ps1, setup.sh, run.ps1
├─ config.example.yaml
└─ pyproject.toml
```

## 6. Windows 로컬 실행 준비
1. Python 3.11+ , Git
2. Visual Studio 2019 Build Tools ("C++를 사용한 데스크톱 개발")
3. `scripts\setup.ps1` → venv 생성, 의존성 설치, gtest 소스 다운로드
4. `copy config.example.yaml config.yaml`, 환경변수에 API 키 설정
5. `mast generate --project examples\calculator\calculator.vcxproj --target src\calculator.cpp`
6. `mast ui`

코드 원칙: `pathlib` 사용, `subprocess`는 리스트 인자(shell 미사용), 출력 인코딩 처리(MSVC 로그 cp949 대비), 경로 공백 처리.

## 7. 구현 순서
| 단계 | 내용 | 완료 기준 |
|---|---|---|
| M1 | 골격, config, LLM 어댑터 2종 | 두 provider로 호출 성공 |
| M2 | 샘플 프로젝트, Analyzer | 함수 목록 JSON 출력 |
| M3 | Planner + Writer | gtest 파일 생성 |
| M4 | Builder (CMake → vcxproj) | 샘플에서 수동 작성 테스트 빌드·실행 |
| M5 | Verifier + Fixer 루프 | 의도적 버그 심은 샘플에서 수정방안 리포트 |
| M6 | CLI, Reporter | end-to-end CLI 동작 |
| M7 | Streamlit UI | UI에서 end-to-end 동작 |

## 8. 리스크
- **vcxproj 다양성**: props 상속(`.props`), 커스텀 매크로 → 1차는 직접 정의된 값 + 주요 매크로만 지원, 미해결 매크로는 경고 후 `config.yaml`에서 수동 보충
- **대상 소스의 외부 의존성**(DB, 하드웨어 SDK 등): 링크 실패 가능 → 1차는 추가 lib/include를 설정으로 지정, 근본 해결은 2단계 gmock
- **LLM 기대값 오판**: 제품 버그와 테스트 오류 구분이 틀릴 수 있음 → 자동 수정은 테스트 코드에만, 제품 코드는 제안만
- **사내 LLM 품질/컨텍스트 길이 차이**: 함수 단위로 분할 호출, 프롬프트에 출력 형식 예시 포함

## 9. 2단계 후보
gmock 모킹, 커버리지(OpenCppCoverage / gcov) 기반 TC 보강, nsfwtest 어댑터, 여러 파일 병렬 처리.
