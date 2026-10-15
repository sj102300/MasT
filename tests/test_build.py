import os
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from fake_responses import TEST_CODE
from mast.build import Builder, BuildSetupError, resolve_backend, run_tests
from mast.build.gtest_source import GTestSourceError, ensure_gtest
from mast.build.results import parse_stdout, parse_xml
from mast.build.vcxproj import VcxTestSpec, defines_main, generate_test_vcxproj, parse_vcxproj
from mast.config import BuildConfig

ROOT = Path(__file__).resolve().parent.parent
CALC = ROOT / "examples" / "calculator"
NS = "{http://schemas.microsoft.com/developer/msbuild/2003}"


def test_parse_sample_vcxproj_debug_and_release():
    dbg = parse_vcxproj(CALC / "calculator.vcxproj", "Debug", "x64")
    assert [p.name for p in dbg.sources] == ["calculator.cpp", "string_utils.cpp", "main.cpp"]
    assert Path(dbg.include_dirs()[0]) == (CALC / "include").resolve()
    assert "CALC_DEMO" in dbg.defines() and "_DEBUG" in dbg.defines()
    assert dbg.clcompile["RuntimeLibrary"] == "MultiThreadedDebugDLL"
    assert dbg.properties["PlatformToolset"] == "v142"
    assert dbg.solution_dir == CALC.resolve()
    rel = parse_vcxproj(CALC / "calculator.vcxproj", "Release", "x64")
    assert "NDEBUG" in rel.defines() and "_DEBUG" not in rel.defines()


def test_vcxproj_conditions_macros_and_exclusions(tmp_path):
    (tmp_path / "a.cpp").write_text("int a() { return 1; }\n")
    proj = tmp_path / "p.vcxproj"
    proj.write_text(r"""<?xml version="1.0" encoding="utf-8"?>
<Project xmlns="http://schemas.microsoft.com/developer/msbuild/2003">
  <PropertyGroup><LibRoot>$(SolutionDir)third\lib</LibRoot></PropertyGroup>
  <PropertyGroup Condition="'$(Configuration)'=='Debug' and '$(Platform)'=='Win32'"><PlatformToolset>v141</PlatformToolset></PropertyGroup>
  <PropertyGroup Condition="'$(Configuration)'=='Debug' and '$(Platform)'=='x64'"><PlatformToolset>v142</PlatformToolset></PropertyGroup>
  <ImportGroup Label="PropertySheets">
    <Import Project="..\common.props" />
    <Import Project="$(UserRootDir)\Microsoft.Cpp.$(Platform).user.props" />
  </ImportGroup>
  <ItemDefinitionGroup>
    <ClCompile>
      <AdditionalIncludeDirectories>inc;$(LibRoot)\include;$(BOOST_ROOT);%(AdditionalIncludeDirectories)</AdditionalIncludeDirectories>
    </ClCompile>
    <Link><AdditionalDependencies>foo.lib;%(AdditionalDependencies)</AdditionalDependencies></Link>
  </ItemDefinitionGroup>
  <ItemGroup>
    <ClCompile Include="a.cpp" />
    <ClCompile Include="b.cpp"><ExcludedFromBuild Condition="'$(Configuration)|$(Platform)'=='Debug|x64'">true</ExcludedFromBuild></ClCompile>
    <ClCompile Include="c.cpp"><ExcludedFromBuild Condition="'$(Configuration)|$(Platform)'=='Release|x64'">true</ExcludedFromBuild></ClCompile>
    <ProjectReference Include="..\lib\lib.vcxproj" />
  </ItemGroup>
</Project>""")
    info = parse_vcxproj(proj, "Debug", "x64")
    assert info.properties["PlatformToolset"] == "v142"
    assert [p.name for p in info.sources] == ["a.cpp", "c.cpp"]
    dirs = info.include_dirs()
    assert Path(dirs[0]) == (tmp_path / "inc").resolve()
    assert dirs[1].replace("\\", "/").endswith("third/lib/include")  # user macro + $(SolutionDir) expanded
    assert dirs[2] == "$(BOOST_ROOT)"  # unknown macro kept for msbuild
    assert info.libs() == ["foo.lib"]
    assert len(info.property_sheets) == 1 and info.property_sheets[0].endswith("common.props")
    assert info.project_references[0].name == "lib.vcxproj"


def test_generate_test_vcxproj_is_valid_xml(tmp_path):
    info = parse_vcxproj(CALC / "calculator.vcxproj", "Debug", "x64")
    gtest = tmp_path / "googletest-1.17.0"
    spec = VcxTestSpec(
        sources=[p for p in info.sources if not defines_main(p)],
        tests=[tmp_path / "tests" / "calculator_test.cpp"], gtest_root=gtest,
        main_file=tmp_path / "mast_main.cpp", include_dirs=info.include_dirs(),
        defines=info.defines(), libs=info.libs(), lib_dirs=[],
    )
    text = generate_test_vcxproj(info, spec)
    root = ET.fromstring(text.encode("utf-8"))
    compiled = [Path(e.get("Include")).name for e in root.iter(f"{NS}ClCompile") if e.get("Include")]
    assert compiled == ["calculator.cpp", "string_utils.cpp", "calculator_test.cpp", "mast_main.cpp", "gtest-all.cc"]
    toolsets = [e.text for e in root.iter(f"{NS}PlatformToolset")]
    assert toolsets == ["v142"]
    incl = next(root.iter(f"{NS}AdditionalIncludeDirectories")).text
    assert str((CALC / "include").resolve()) in incl and str(gtest / "googletest" / "include") in incl
    assert next(root.iter(f"{NS}RuntimeLibrary")).text == "MultiThreadedDebugDLL"
    assert next(root.iter(f"{NS}LanguageStandard")).text == "stdcpp17"
    assert "v143" in generate_test_vcxproj(info, spec, toolset="v143")


def test_defines_main():
    assert defines_main(CALC / "src" / "main.cpp")
    assert not defines_main(CALC / "src" / "calculator.cpp")


def test_resolve_backend(tmp_path):
    assert resolve_backend("auto", CALC / "calculator.vcxproj")[0] == "vcxproj"
    assert resolve_backend("cmake", CALC / "calculator.vcxproj") == ("cmake", CALC.resolve())
    expected = "vcxproj" if os.name == "nt" else "cmake"
    assert resolve_backend("auto", CALC)[0] == expected
    (tmp_path / "a.vcxproj").write_text("<Project/>")
    (tmp_path / "b.vcxproj").write_text("<Project/>")
    with pytest.raises(BuildSetupError):
        resolve_backend("vcxproj", tmp_path)


def test_parse_gtest_xml(tmp_path):
    xml = tmp_path / "r.xml"
    xml.write_text("""<?xml version="1.0" encoding="UTF-8"?>
<testsuites tests="3" failures="1">
  <testsuite name="CalcTest" tests="3">
    <testcase name="A" status="run" result="completed" time="0.001" classname="CalcTest" />
    <testcase name="B" status="run" result="completed" time="0" classname="CalcTest">
      <failure message="x.cpp:3&#x0A;Expected equality" type=""><![CDATA[x.cpp:3
Expected equality of these values]]></failure>
    </testcase>
    <testcase name="C" status="run" result="skipped" time="0" classname="CalcTest"><skipped message=""/></testcase>
  </testsuite>
</testsuites>""")
    cases = parse_xml(xml)
    assert [(c.name, c.status) for c in cases] == [("A", "passed"), ("B", "failed"), ("C", "skipped")]
    assert "Expected equality" in cases[1].message


def test_parse_stdout_detects_crash():
    out = """[==========] Running 3 tests from 1 test suite.
[ RUN      ] S.Ok
[       OK ] S.Ok (0 ms)
[ RUN      ] S.Fails
x.cpp:5: Failure
Value of: f()
[  FAILED  ] S.Fails (0 ms)
[ RUN      ] S.Crashes
Segmentation fault
"""
    cases = parse_stdout(out)
    assert [(c.full_name, c.status) for c in cases] == [
        ("S.Ok", "passed"), ("S.Fails", "failed"), ("S.Crashes", "crashed")]
    assert "Segmentation fault" in cases[2].message


def test_bad_gtest_source_dir(tmp_path):
    with pytest.raises(GTestSourceError):
        ensure_gtest(str(tmp_path), tmp_path, "http://invalid")


# -- integration: real compiler (skipped when unavailable) --------------------------------

def _gtest_root(tmp_path_factory):
    local = os.environ.get("MAST_GTEST_DIR")
    cache = Path(os.environ.get("MAST_CACHE_DIR", "~/.mast/cache")).expanduser()
    try:
        return ensure_gtest(local, cache, BuildConfig().gtest_url)
    except GTestSourceError as e:
        pytest.skip(f"googletest unavailable: {e}")


needs_toolchain = pytest.mark.skipif(
    shutil.which("cmake") is None or (os.name != "nt" and shutil.which("c++") is None),
    reason="cmake / C++ compiler not installed",
)


@needs_toolchain
@pytest.mark.parametrize("cmake_target", [None, "calculator_lib"])
def test_cmake_build_and_run_sample(tmp_path, tmp_path_factory, cmake_target):
    gtest = _gtest_root(tmp_path_factory)
    test_file = tmp_path / "tests" / "calculator_test.cpp"
    test_file.parent.mkdir()
    test_file.write_text(TEST_CODE, encoding="utf-8-sig")
    cfg = BuildConfig(system="cmake", gtest_source_dir=str(gtest), cmake_target=cmake_target)
    builder = Builder(cfg, CALC)
    builder.prepare(tmp_path / "build", [test_file])
    result = builder.build(tmp_path / "build", timeout=900)
    assert result.ok, result.log[-3000:]
    run = run_tests(result.exe, tmp_path / "build", timeout=60)
    status = {c.full_name: c.status for c in run.cases}
    assert status == {
        "CalculatorTest.AddPositive": "passed",
        "CalculatorTest.DivideByZeroThrows": "passed",
        "CalculatorTest.FactorialOfZeroIsOne": "failed",  # the planted bug
        "CalculatorTest.FactorialOfFive": "passed",
    }
    assert run.xml_found and not run.crashed
