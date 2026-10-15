from pathlib import Path

from mast.analyzer import analyze_files, analyze_target, find_related_files

ROOT = Path(__file__).resolve().parent.parent
CALC = ROOT / "examples" / "calculator"


def _by_name(result):
    return {f.qualified_name: f for f in result.functions}


def test_find_related_files_pairs_header():
    files = find_related_files(CALC / "src" / "calculator.cpp", [])
    names = [p.name for p in files]
    assert names == ["calculator.cpp", "calculator.h"]


def test_analyze_calculator_merges_decl_and_def():
    result = analyze_target(CALC / "src" / "calculator.cpp", CALC)
    fns = _by_name(result)
    add = fns["calc::Calculator::add"]
    assert add.kind == "method" and add.class_name == "Calculator" and add.namespace == "calc"
    assert add.is_const and add.param_count == 2
    assert add.decl_file == "include/calculator.h" and add.def_file == "src/calculator.cpp"
    assert "return a + b" in add.body
    assert "Returns a + b" in add.comment

    fact = fns["calc::Calculator::factorial"]
    assert fact.is_static and "uint64_t" in fact.return_type

    testable = {f.qualified_name for f in result.testable_functions()}
    assert "calc::Calculator::divide" in testable
    assert "calc::Calculator::Calculator" not in testable  # defaulted ctor
    assert [c.qualified_name for c in result.classes] == ["calc::Calculator"]


def test_private_and_internal_functions_excluded():
    result = analyze_target(CALC / "src" / "string_utils.cpp", CALC)
    fns = _by_name(result)
    assert fns["strutil::isSpace"].internal_linkage
    testable = {f.qualified_name for f in result.testable_functions()}
    assert testable == {"strutil::trim", "strutil::split", "strutil::toUpper", "strutil::startsWith"}
    assert fns["strutil::split"].decl_file == "include/string_utils.h"


def test_main_excluded():
    result = analyze_files([CALC / "src" / "main.cpp"], CALC)
    assert result.testable_functions() == []


def test_parser_edge_cases(tmp_path):
    src = tmp_path / "edge.h"
    src.write_text(
        """
namespace a::b {
struct Point { int x; int y; int sum() const { return x + y; } };
class Base {
public:
    virtual ~Base();
    virtual int run() = 0;
    Base& operator=(const Base&) = delete;
    template <typename T> T twice(T v) const { return v * 2; }
protected:
    void hook();
};
int* makeArray(int n);
}
int a::b::Base::run() { return 1; }
static int helper() { return 0; }
""",
        encoding="utf-8",
    )
    result = analyze_files([src], tmp_path)
    fns = _by_name(result)
    assert fns["a::b::Point::sum"].access == "public"  # struct default
    assert fns["a::b::Base::hook"].access == "protected"
    assert fns["a::b::Base::twice"].is_template
    assert fns["a::b::makeArray"].return_type == "int*"
    assert fns["a::b::Base::run"].body  # pure virtual with out-of-line definition
    assert fns["a::b::Base::operator="].is_deleted_or_default
    assert fns["helper"].internal_linkage
    testable = {f.qualified_name for f in result.testable_functions()}
    assert testable == {"a::b::Point::sum", "a::b::Base::run", "a::b::Base::twice", "a::b::makeArray"}


def test_cp949_source(tmp_path):
    src = tmp_path / "kr.cpp"
    src.write_bytes("// 한글 주석\nint f(int x) { return x; }\n".encode("cp949"))
    result = analyze_files([src], tmp_path)
    assert result.functions[0].comment == "// 한글 주석"
