"""Read a Visual Studio .vcxproj and generate a test .vcxproj that reuses its settings."""
from __future__ import annotations

import re
import uuid
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

_NS = "{http://schemas.microsoft.com/developer/msbuild/2003}"
_MACRO_RE = re.compile(r"\$\(([A-Za-z_][A-Za-z0-9_.]*)\)")
_ITEM_META_RE = re.compile(r"%\([^)]*\)")
_CMP_RE = re.compile(r"""^\s*'([^']*)'\s*(==|!=)\s*'([^']*)'\s*$""")


def _tag(el: ET.Element) -> str:
    return el.tag[len(_NS):] if el.tag.startswith(_NS) else el.tag


def _children(el: ET.Element, name: str) -> list[ET.Element]:
    return [c for c in el if _tag(c) == name]


@dataclass
class VcxprojInfo:
    path: Path
    configuration: str
    platform: str
    properties: dict[str, str] = field(default_factory=dict)
    clcompile: dict[str, str] = field(default_factory=dict)
    link: dict[str, str] = field(default_factory=dict)
    sources: list[Path] = field(default_factory=list)
    headers: list[Path] = field(default_factory=list)
    property_sheets: list[str] = field(default_factory=list)
    project_references: list[Path] = field(default_factory=list)
    solution_dir: Path | None = None
    warnings: list[str] = field(default_factory=list)

    @property
    def project_dir(self) -> Path:
        return self.path.parent

    def include_dirs(self) -> list[str]:
        return self._paths(self.clcompile.get("AdditionalIncludeDirectories", ""))

    def lib_dirs(self) -> list[str]:
        return self._paths(self.link.get("AdditionalLibraryDirectories", ""))

    def defines(self) -> list[str]:
        return _split(self.clcompile.get("PreprocessorDefinitions", ""))

    def libs(self) -> list[str]:
        return _split(self.link.get("AdditionalDependencies", ""))

    def _paths(self, value: str) -> list[str]:
        return [_absolute(p, self.project_dir) for p in _split(value)]


def _split(value: str) -> list[str]:
    value = _ITEM_META_RE.sub("", value)
    return [v.strip() for v in value.split(";") if v.strip()]


def _absolute(p: str, base: Path) -> str:
    """Make a project-relative path absolute; keep unresolved $(Macros) for msbuild."""
    if "$(" in p:
        return p
    path = Path(p.replace("\\", "/"))
    if not path.is_absolute() and not re.match(r"^[A-Za-z]:", p):
        path = (base / path).resolve()
    return str(path)


def find_solution_dir(project_dir: Path) -> Path | None:
    for d in [project_dir, *project_dir.parents][:4]:
        if any(d.glob("*.sln")):
            return d
    return None


class _Evaluator:
    def __init__(self, info: VcxprojInfo):
        self.info = info

    def builtins(self) -> dict[str, str]:
        pdir = str(self.info.project_dir.resolve())
        sdir = str((self.info.solution_dir or self.info.project_dir).resolve())
        sep = "\\" if "\\" in pdir or re.match(r"^[A-Za-z]:", pdir) else "/"
        return {
            "configuration": self.info.configuration,
            "platform": self.info.platform,
            "projectdir": pdir.rstrip("\\/") + sep,
            "msbuildprojectdirectory": pdir.rstrip("\\/"),
            "msbuildthisfiledirectory": pdir.rstrip("\\/") + sep,
            "solutiondir": sdir.rstrip("\\/") + sep,
            "projectname": self.info.path.stem,
            "msbuildprojectname": self.info.path.stem,
        }

    def expand(self, value: str, depth: int = 0) -> str:
        if "$(" not in value or depth > 8:
            return value
        builtins = self.builtins()
        props = {k.lower(): v for k, v in self.info.properties.items()}

        def repl(m: re.Match) -> str:
            key = m.group(1).lower()
            if key in builtins:
                return builtins[key]
            if key in props:
                return self.expand(props[key], depth + 1)
            return m.group(0)  # env var or msbuild-known property: leave for msbuild

        return _MACRO_RE.sub(repl, value)

    def condition(self, cond: str | None) -> bool:
        if not cond:
            return True
        text = self.expand(cond)
        if re.search(r"\bexists\s*\(", text, re.I):
            return True
        for clause in re.split(r"\s+or\s+", text, flags=re.I):
            parts = re.split(r"\s+and\s+", clause, flags=re.I)
            ok = True
            for part in parts:
                m = _CMP_RE.match(part.strip().strip("()"))
                if not m:
                    continue  # unknown expression: treat as true
                left, op, right = m.group(1).lower(), m.group(2), m.group(3).lower()
                ok = ok and ((left == right) if op == "==" else (left != right))
            if ok:
                return True
        return False


def parse_vcxproj(path: Path, configuration: str = "Debug", platform: str = "x64") -> VcxprojInfo:
    path = path.resolve()
    info = VcxprojInfo(path=path, configuration=configuration, platform=platform)
    info.solution_dir = find_solution_dir(path.parent)
    ev = _Evaluator(info)
    root = ET.parse(path).getroot()

    configs = []
    for group in _children(root, "ItemGroup"):
        for pc in _children(group, "ProjectConfiguration"):
            configs.append(pc.get("Include", ""))
    wanted = f"{configuration}|{platform}"
    if configs and wanted not in configs:
        info.warnings.append(f"{wanted} not in project configurations {configs}")

    for el in root:
        tag = _tag(el)
        if not ev.condition(el.get("Condition")):
            continue
        if tag == "PropertyGroup":
            for prop in el:
                if ev.condition(prop.get("Condition")):
                    info.properties[_tag(prop)] = (prop.text or "").strip()
        elif tag == "ItemDefinitionGroup":
            for kind in el:
                target = {"ClCompile": info.clcompile, "Link": info.link}.get(_tag(kind))
                if target is None:
                    continue
                for setting in kind:
                    if ev.condition(setting.get("Condition")):
                        target[_tag(setting)] = ev.expand((setting.text or "").strip())
        elif tag == "ImportGroup" and el.get("Label") == "PropertySheets":
            for imp in _children(el, "Import"):
                proj = imp.get("Project", "")
                if "$(UserRootDir)" in proj or not ev.condition(imp.get("Condition")):
                    continue
                info.property_sheets.append(_absolute(ev.expand(proj), path.parent))
        elif tag == "ItemGroup":
            for item in el:
                itag = _tag(item)
                include = item.get("Include", "")
                if not include or not ev.condition(item.get("Condition")):
                    continue
                excluded = any(
                    (x.text or "").strip().lower() == "true" and ev.condition(x.get("Condition"))
                    for x in _children(item, "ExcludedFromBuild")
                )
                if excluded:
                    continue
                resolved = Path(_absolute(ev.expand(include), path.parent))
                if itag == "ClCompile":
                    info.sources.append(resolved)
                elif itag == "ClInclude":
                    info.headers.append(resolved)
                elif itag == "ProjectReference":
                    info.project_references.append(resolved)
    return info


_MAIN_RE = re.compile(r"\b(?:int|void|auto)\s+(?:__\w+\s+)?(?:w?main|_tmain|w?WinMain)\s*\(")


def defines_main(path: Path) -> bool:
    try:
        text = path.read_bytes().decode("utf-8", errors="replace")
    except OSError:
        return False
    return bool(_MAIN_RE.search(text))


@dataclass
class VcxTestSpec:
    sources: list[Path]
    tests: list[Path]
    gtest_root: Path
    main_file: Path
    include_dirs: list[str]
    defines: list[str]
    libs: list[str]
    lib_dirs: list[str]


def _elem(tag: str, value: str | None, indent: str = "      ") -> str:
    return f"{indent}<{tag}>{escape(value)}</{tag}>\n" if value else ""


_LANG_ORDER = ["stdcpp14", "stdcpp17", "stdcpp20", "stdcpplatest"]


def generate_test_vcxproj(info: VcxprojInfo, spec: VcxTestSpec, toolset: str | None = None) -> str:
    props = info.properties
    cl = info.clcompile
    lang = cl.get("LanguageStandard") or "stdcpp17"
    if lang not in _LANG_ORDER or _LANG_ORDER.index(lang) < 1:
        lang = "stdcpp17"
    gtest = spec.gtest_root / "googletest"
    includes = spec.include_dirs + [str(gtest / "include"), str(gtest)]
    configuration, platform = info.configuration, info.platform
    debug = props.get("UseDebugLibraries", "true" if configuration.lower() == "debug" else "false")
    guid = "{" + str(uuid.uuid5(uuid.NAMESPACE_URL, str(info.path))).upper() + "}"

    def items(paths: list[Path], extra: str = "") -> str:
        out = ""
        for p in paths:
            if extra:
                out += f"    <ClCompile Include={quoteattr(str(p))}>\n{extra}    </ClCompile>\n"
            else:
                out += f"    <ClCompile Include={quoteattr(str(p))} />\n"
        return out

    sheets = ""
    for s in info.property_sheets:
        cond = quoteattr("exists('" + s + "')")
        sheets += f"    <Import Project={quoteattr(s)} Condition={cond} />\n"
    refs = "".join(
        f"    <ProjectReference Include={quoteattr(str(r))} />\n" for r in info.project_references
    )
    gtest_item_meta = "      <WarningLevel>Level3</WarningLevel>\n      <TreatWarningAsError>false</TreatWarningAsError>\n"

    return f"""<?xml version="1.0" encoding="utf-8"?>
<!-- Generated by MasT from {escape(str(info.path))}. Do not edit; regenerated on every run. -->
<Project DefaultTargets="Build" ToolsVersion="16.0" xmlns="http://schemas.microsoft.com/developer/msbuild/2003">
  <ItemGroup Label="ProjectConfigurations">
    <ProjectConfiguration Include="{configuration}|{platform}">
      <Configuration>{configuration}</Configuration>
      <Platform>{platform}</Platform>
    </ProjectConfiguration>
  </ItemGroup>
  <PropertyGroup Label="Globals">
    <VCProjectVersion>16.0</VCProjectVersion>
    <ProjectGuid>{guid}</ProjectGuid>
    <RootNamespace>mast_tests</RootNamespace>
    <ProjectName>mast_tests</ProjectName>
{_elem("WindowsTargetPlatformVersion", props.get("WindowsTargetPlatformVersion") or "10.0", "    ")}  </PropertyGroup>
  <Import Project="$(VCTargetsPath)\\Microsoft.Cpp.Default.props" />
  <PropertyGroup Label="Configuration">
    <ConfigurationType>Application</ConfigurationType>
    <UseDebugLibraries>{escape(debug)}</UseDebugLibraries>
    <PlatformToolset>{escape(toolset or props.get("PlatformToolset") or "v142")}</PlatformToolset>
{_elem("CharacterSet", props.get("CharacterSet"), "    ")}{_elem("UseOfMfc", props.get("UseOfMfc"), "    ")}{_elem("UseOfAtl", props.get("UseOfAtl"), "    ")}  </PropertyGroup>
  <Import Project="$(VCTargetsPath)\\Microsoft.Cpp.props" />
  <ImportGroup Label="PropertySheets">
    <Import Project="$(UserRootDir)\\Microsoft.Cpp.$(Platform).user.props" Condition="exists('$(UserRootDir)\\Microsoft.Cpp.$(Platform).user.props')" Label="LocalAppDataPlatform" />
{sheets}  </ImportGroup>
  <PropertyGroup>
    <OutDir>$(ProjectDir)bin\\</OutDir>
    <IntDir>$(ProjectDir)obj\\</IntDir>
    <TargetName>mast_tests</TargetName>
    <LinkIncremental>false</LinkIncremental>
  </PropertyGroup>
  <ItemDefinitionGroup>
    <ClCompile>
      <PrecompiledHeader>NotUsing</PrecompiledHeader>
      <WarningLevel>{escape(cl.get("WarningLevel") or "Level3")}</WarningLevel>
      <LanguageStandard>{lang}</LanguageStandard>
      <AdditionalIncludeDirectories>{escape(";".join(includes))};%(AdditionalIncludeDirectories)</AdditionalIncludeDirectories>
      <PreprocessorDefinitions>{escape(";".join(spec.defines))};%(PreprocessorDefinitions)</PreprocessorDefinitions>
{_elem("RuntimeLibrary", cl.get("RuntimeLibrary"))}{_elem("ForcedIncludeFiles", cl.get("ForcedIncludeFiles"))}{_elem("ConformanceMode", cl.get("ConformanceMode"))}{_elem("SDLCheck", cl.get("SDLCheck"))}{_elem("DisableSpecificWarnings", cl.get("DisableSpecificWarnings"))}      <AdditionalOptions>/bigobj {escape(_ITEM_META_RE.sub("", cl.get("AdditionalOptions", "")).strip())} %(AdditionalOptions)</AdditionalOptions>
      <MultiProcessorCompilation>true</MultiProcessorCompilation>
      <TreatWarningAsError>false</TreatWarningAsError>
      <DebugInformationFormat>ProgramDatabase</DebugInformationFormat>
    </ClCompile>
    <Link>
      <SubSystem>Console</SubSystem>
      <GenerateDebugInformation>true</GenerateDebugInformation>
      <AdditionalDependencies>{escape(";".join(spec.libs))};%(AdditionalDependencies)</AdditionalDependencies>
      <AdditionalLibraryDirectories>{escape(";".join(spec.lib_dirs))};%(AdditionalLibraryDirectories)</AdditionalLibraryDirectories>
    </Link>
  </ItemDefinitionGroup>
  <ItemGroup>
    <!-- product sources -->
{items(spec.sources)}    <!-- generated tests -->
{items(spec.tests)}    <!-- test runner main + googletest -->
{items([spec.main_file])}{items([gtest / "src" / "gtest-all.cc"], gtest_item_meta)}  </ItemGroup>
  <ItemGroup>
{refs}  </ItemGroup>
  <Import Project="$(VCTargetsPath)\\Microsoft.Cpp.targets" />
</Project>
"""
