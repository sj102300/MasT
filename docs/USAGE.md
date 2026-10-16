# MasT 사용 가이드 (로컬 PC 설치 · 실행)

Windows 10/11 + Visual Studio 2019 기준. Linux(Rocky 10)는 [8. Linux](#8-linux-rocky-linux-10) 참고.

> `main` 브랜치에 구현 PR들이 머지된 상태를 기준으로 한다. 머지 전이면 `git clone` 후 `git checkout docs/usage` 로 최신 코드를 받는다.

목차
1. [준비물 설치](#1-준비물-설치)
2. [MasT 설치](#2-mast-설치)
3. [API 키 / LLM 설정](#3-api-키--llm-설정)
4. [동작 확인 (샘플 프로젝트)](#4-동작-확인-샘플-프로젝트)
5. [내 프로젝트에 적용](#5-내-프로젝트에-적용)
6. [웹 UI](#6-웹-ui)
7. [결과 보는 법](#7-결과-보는-법)
8. [Linux (Rocky Linux 10)](#8-linux-rocky-linux-10)
9. [설정 레퍼런스](#9-설정-레퍼런스)
10. [문제 해결](#10-문제-해결)

---

## 1. 준비물 설치

| 항목 | 버전 | 확인 명령 (PowerShell) | 비고 |
|---|---|---|---|
| Python | 3.11 이상 | `py -3 --version` | [python.org](https://www.python.org/downloads/) 설치 시 **"Add python.exe to PATH"** 체크 |
| Git | 아무 버전 | `git --version` | 레포 클론, googletest 다운로드 폴백 |
| Visual Studio 2019 또는 Build Tools 2019 | 16.x | 아래 참고 | 워크로드 **"C++를 사용한 데스크톱 개발"** |
| Windows SDK | 10.0.x | VS Installer에서 확인 | 위 워크로드에 기본 포함 |
| CMake | 3.20 이상 (선택) | `cmake --version` | Windows에서 vcxproj만 쓰면 불필요 |

Visual Studio 설치 확인:
```powershell
& "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe" -latest -find "MSBuild\**\Bin\MSBuild.exe"
```
경로가 하나 출력되면 정상. MasT는 이 방법으로 msbuild를 자동으로 찾는다.

> VS2022만 설치되어 있다면 [설정](#9-설정-레퍼런스)에서 `build.toolset: v143`으로 바꾼다.

---

## 2. MasT 설치

```powershell
git clone https://github.com/sj102300/MasT.git
cd MasT
powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
```

`setup.ps1`이 하는 일:
1. `.venv` 가상환경 생성 (Python 3.11+ 확인)
2. MasT와 의존성 설치 (`pip install -e ".[dev,web]"`)
3. `config.example.yaml` → `config.yaml` 복사 (이미 있으면 건너뜀)

가상환경 활성화 (새 터미널을 열 때마다):
```powershell
.\.venv\Scripts\Activate.ps1
mast --help
```

> `Activate.ps1` 실행이 막히면 한 번만:
> `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`
> 또는 활성화 없이 `.\.venv\Scripts\mast.exe` 로 직접 실행해도 된다.

수동 설치를 원하면:
```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev,web]"
copy config.example.yaml config.yaml
```

---

## 3. API 키 / LLM 설정

### Claude API (기본값)
```powershell
# 현재 터미널에만
$env:ANTHROPIC_API_KEY = "sk-ant-..."
# 영구 저장 (새 터미널부터 적용)
setx ANTHROPIC_API_KEY "sk-ant-..."
```
`config.yaml`은 기본값 그대로 두면 된다 (`provider: anthropic`, `model: claude-opus-5-5`).

### 사내 LLM (OpenAI 호환)
`config.yaml`의 `llm` 섹션 수정:
```yaml
llm:
  provider: openai_compat
  model: <사내 모델 이름>
  base_url: https://<사내 LLM 주소>/v1
  api_key_env: CORP_LLM_API_KEY      # 이 이름의 환경변수에서 키를 읽음
  temperature: 0.2
  ca_bundle: C:\certs\corp-ca.pem    # 사내 인증서가 필요할 때
  proxy: null                        # 필요 시 http://proxy.corp:8080
```
```powershell
setx CORP_LLM_API_KEY "<키>"
```

### 연결 확인
```powershell
mast check-llm
# provider=anthropic model=claude-opus-5-5 base_url=(default)
# reply: 'OK' (in=.., out=..)
```

---

## 4. 동작 확인 (샘플 프로젝트)

레포에 샘플 `examples\calculator` (VS2019 sln/vcxproj + CMake)가 들어 있다.
`Calculator::factorial(0)`이 0을 반환하는 **버그가 일부러** 들어 있다 (정답 1).

### 4-1. 툴체인 확인 (LLM 사용 안 함)
```powershell
mast selftest --project examples\calculator\calculator.vcxproj
```
기대 출력:
```
backend: vcxproj (...\examples\calculator\calculator.vcxproj)
building... (first build also compiles googletest)
  passed   CalculatorTest.AddPositive
  passed   CalculatorTest.DivideByZeroThrows
  failed   CalculatorTest.FactorialOfZeroIsOne
  passed   CalculatorTest.FactorialOfFive
OK: toolchain works (FactorialOfZeroIsOne fails on purpose: planted bug)
```
- 첫 실행 시 googletest 소스를 `%USERPROFILE%\.mast\cache`에 받는다 (1회)
- 실패하면 [10. 문제 해결](#10-문제-해결)

### 4-2. 함수 목록 확인 (LLM 사용 안 함)
```powershell
mast analyze examples\calculator\src\calculator.cpp --root examples\calculator
```

### 4-3. 전체 실행 (LLM 사용)
```powershell
mast generate examples\calculator\src\calculator.cpp -p examples\calculator\calculator.vcxproj
```
진행:
```
[analyze] 9 testable functions
[plan] Designing test cases
[write] Wrote tests/calculator_test.cpp
[build] [0] Building (vcxproj)
[test] [0] Running tests
[verify] [0] 실패 1건 / 통과 N건 / 전체 N건
[fix] [0] Judging 1 failed tests
...
결과: product_bugs - ... 남은 실패는 모두 제품 코드 버그 의심
  [product_bug] CalculatorTest.FactorialOf...: ...
Report: runs\20261016-...-calculator\report.md
```
LLM이 매번 다른 테스트를 만들기 때문에 테스트 개수와 이름은 실행마다 다르다. factorial(0) 실패가 `product_bug`로 판정되면 정상이다.

---

## 5. 내 프로젝트에 적용

### 기본
```powershell
mast generate <테스트할 .cpp 경로> -p <제품 .vcxproj 경로>
```
예:
```powershell
mast generate D:\work\engine\src\parser.cpp -p D:\work\engine\engine.vcxproj
```

| 옵션 | 설명 |
|---|---|
| `-p, --project` | 빌드에 쓸 `.vcxproj` 파일 (또는 CMake 프로젝트 폴더) |
| `-f, --function` | 특정 함수만. 여러 번 지정 가능: `-f parse -f tokenize` |
| `--root` | 분석 기준 폴더 (기본: vcxproj가 있는 폴더) |
| `-I, --include` | 짝 헤더/소스를 찾을 추가 폴더 |
| `--no-build` | 테스트 코드 생성까지만 (빌드 안 함) |
| `-c, --config` | 다른 설정 파일 사용 |

### 동작 방식
- 대상 `.cpp`와 같은 이름의 헤더(`.h/.hpp`)를 자동으로 찾아 함께 분석
- public 함수/메서드만 대상 (private, static 내부 함수, `main` 제외)
- 제품 `.vcxproj`의 include 경로·전처리기 정의·런타임 라이브러리·속성 시트(.props)·프로젝트 참조를 읽어
  `runs\<run>\build\mast_tests.vcxproj`를 따로 만들어 빌드한다. **원본 sln/vcxproj와 제품 코드는 수정하지 않는다.**
- 빌드에 포함되는 제품 소스: vcxproj의 ClCompile 목록 중 `main()`이 있는 파일 제외

### 빌드가 안 될 때 보충하는 법
결과가 `env_error`면 출력되는 힌트대로 `config.yaml`의 `build` 섹션에 추가한다.
```yaml
build:
  include_dirs: ["D:/libs/boost_1_80"]       # C1083: 헤더를 찾을 수 없음
  defines: ["MY_FEATURE=1"]
  sources: ["src/**/*.cpp"]                 # 비우면 vcxproj의 소스 목록 사용
  libs: ["ws2_32.lib", "mylib.lib"]         # LNK2019: 정의를 찾을 수 없음
  lib_dirs: ["D:/libs/mylib/x64/Debug"]
  configuration: Debug
  platform: x64                             # Win32 프로젝트면 Win32
```

---

## 6. 웹 UI

```powershell
mast ui                       # 브라우저에서 http://localhost:8501
mast ui --port 8600 -c config.yaml
```
- **새 실행** 탭: 프로젝트 경로(.vcxproj 또는 폴더) 입력 → 대상 파일 선택 → 함수 선택 → `테스트 생성 시작`
- **실행 기록** 탭: 지난 실행 결과 보기
- 결과 탭: 리포트 / 테스트 코드(다운로드, 수정 이력) / TC 계획 / 빌드 로그 / 테스트 출력 / LLM 호출 내역
- 사이드바에서 LLM·빌드 설정을 이번 실행에만 바꿀 수 있다 (파일은 수정되지 않음)
- 종료: 터미널에서 `Ctrl+C`

---

## 7. 결과 보는 법

### 결과 종류
| outcome | 의미 | 할 일 |
|---|---|---|
| `pass` | 모든 테스트 통과 | 생성된 테스트를 프로젝트에 가져가서 사용 |
| `product_bugs` | 남은 실패가 모두 **제품 코드 버그 의심** | 리포트의 위치·수정 제안 검토 |
| `unresolved` | 최대 수정 횟수 도달 / 같은 실패 반복 / 판단 필요 | 리포트와 `llm_calls.jsonl` 확인 |
| `env_error` | include·링크·툴셋 등 설정 문제 | 힌트대로 `config.yaml` 보충 후 재실행 |

### 결과 폴더 `runs\<시각>-<파일명>\`
| 파일 | 내용 |
|---|---|
| `report.md` | **먼저 볼 것.** 결과 요약, 제품 버그 수정 제안, TC 표, 진행 이력 |
| `tests\*_test.cpp` | 최종 테스트 코드 |
| `history\` | 수정 단계별 버전 (v0 = 최초 생성) |
| `plan.json` | TC 계획 (입력, 기대값, 분류) |
| `build\mast_tests.vcxproj` | 생성된 테스트 프로젝트 (VS에서 열어 디버깅 가능) |
| `build.log`, `test_output.log` | 빌드 / 실행 로그 |
| `llm_calls.jsonl` | LLM 요청·응답 전체 |
| `usage.json` | 토큰 사용량 |

리포트 다시 만들기: `mast report runs\<run>`

### 생성된 테스트를 내 프로젝트에서 쓰기
`build\mast_tests.vcxproj`를 VS에서 열면 바로 빌드·디버깅할 수 있다. 정식으로 넣을 때는 `tests\*_test.cpp`를 기존 테스트 프로젝트에 추가한다 (googletest 필요, `main()`은 gtest_main 또는 기존 것 사용).

---

## 8. Linux (Rocky Linux 10)

```bash
sudo dnf install -y python3 python3-pip git cmake gcc-c++   # python3 --version 이 3.11 이상인지 확인
git clone https://github.com/sj102300/MasT.git && cd MasT
./scripts/setup.sh
source .venv/bin/activate
export ANTHROPIC_API_KEY=sk-ant-...

mast selftest                                         # 샘플 CMake 빌드 확인
mast generate examples/calculator/src/calculator.cpp -p examples/calculator
```
- `-p`에 CMake 프로젝트 폴더를 준다. 기본은 제품 소스를 직접 컴파일한다
- 제품 CMake에 라이브러리 타깃이 있으면 링크하는 편이 정확하다:
  ```yaml
  build:
    cmake_target: calculator_lib
  ```

---

## 9. 설정 레퍼런스

`config.yaml` 전체 예시는 [config.example.yaml](../config.example.yaml).

| 키 | 기본값 | 설명 |
|---|---|---|
| `llm.provider` | `anthropic` | `anthropic` / `openai_compat` |
| `llm.model` | `claude-opus-5-5` | 모델 이름 |
| `llm.api_key_env` | `ANTHROPIC_API_KEY` | 키를 읽을 환경변수 이름 |
| `llm.base_url` | null | `openai_compat`일 때 필수 |
| `llm.effort` | `high` | Claude 전용: 사고 깊이 (`low`~`max`) |
| `llm.ca_bundle` / `llm.proxy` | null | 사내 인증서 / 프록시 |
| `agents.<planner\|writer\|fixer>` | - | 에이전트별 모델 등 덮어쓰기 |
| `run.output_dir` | `runs` | 결과 폴더 |
| `run.max_fix_iterations` | 3 | 빌드-수정 반복 최대 횟수 |
| `run.language` | `Korean` | TC 설명·판정 사유 언어 |
| `run.build_timeout_sec` / `test_timeout_sec` | 1800 / 120 | 타임아웃 |
| `build.system` | `auto` | `auto` / `vcxproj` / `cmake` |
| `build.configuration` / `platform` | `Debug` / `x64` | vcxproj 구성 |
| `build.toolset` | null | PlatformToolset 덮어쓰기 (예: `v143`) |
| `build.msbuild_path` | null | msbuild 직접 지정 |
| `build.include_dirs` / `defines` / `libs` / `lib_dirs` / `sources` | [] | 자동으로 못 읽는 빌드 설정 보충 |
| `build.gtest_source_dir` | null | googletest 소스 폴더 (오프라인용) |
| `build.cache_dir` | `~/.mast/cache` | googletest 다운로드 위치 |

프롬프트 수정: `mast\prompts\*.md` (planner, writer, fixer_build, fixer_judge, fixer_tests)

---

## 10. 문제 해결

| 증상 | 원인 / 해결 |
|---|---|
| `mast`를 찾을 수 없음 | 가상환경 미활성화 → `.\.venv\Scripts\Activate.ps1` |
| `Activate.ps1` 실행 차단 | `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` |
| `Python 3.11+ required` | 최신 Python 설치 후 `.venv` 폴더 삭제하고 `setup.ps1` 재실행 |
| `No Claude API credentials` | `$env:ANTHROPIC_API_KEY` 설정. `setx`로 저장했다면 **새 터미널**에서 실행 |
| `Authentication failed` | 키 값 또는 `api_key_env` 이름 확인 |
| `Connection error` / SSL 에러 | 사내망: `llm.proxy`, `llm.ca_bundle` 지정 |
| `MSBuild not found` | VS2019 Build Tools "C++를 사용한 데스크톱 개발" 설치, 또는 `build.msbuild_path` 지정 |
| `MSB8020` (toolset 없음) | 설치된 VS 버전에 맞게 `build.toolset: v142`(2019) / `v143`(2022) |
| `MSB8036` (SDK 없음) | VS Installer에서 Windows 10/11 SDK 설치 |
| `Could not obtain googletest` | [googletest v1.17.0 zip](https://github.com/google/googletest/archive/refs/tags/v1.17.0.zip)을 받아 압축 해제 후 `build.gtest_source_dir: C:/libs/googletest-1.17.0` |
| `C1083` 헤더를 찾을 수 없음 | `build.include_dirs`에 경로 추가 |
| `LNK2019` / `LNK2001` 정의 없음 | 해당 함수가 있는 소스를 `build.sources`에, 라이브러리를 `build.libs`/`lib_dirs`에 추가 |
| `No testable functions found` | 대상 파일에 public 함수가 없음. 헤더/소스 짝이 다른 폴더면 `-I <폴더>` |
| `unresolved` 반복 | `max_fix_iterations` 늘리기, `llm_calls.jsonl`로 원인 확인, 프롬프트 조정 |
| 콘솔 한글 깨짐 | `chcp 65001` 후 실행 |

문제 보고 시 함께 주면 좋은 것: `runs\<run>\build.log`, `report.md`, 실행한 명령.

---

## 부록: MasT 자체 테스트 실행

```powershell
pytest
```
- CMake와 C++ 컴파일러가 없으면 실제 빌드 테스트는 자동으로 건너뛴다
- googletest를 이미 받아둔 경우: `$env:MAST_GTEST_DIR = "C:\libs\googletest-1.17.0"`
