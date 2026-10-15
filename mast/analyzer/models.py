from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Access = Literal["public", "protected", "private"]
Kind = Literal["free", "method", "ctor", "dtor", "operator"]


class FunctionInfo(BaseModel):
    name: str
    qualified_name: str
    namespace: str = ""
    class_name: str = ""
    kind: Kind = "free"
    return_type: str = ""
    parameters: str = "()"
    param_count: int = 0
    signature: str = ""
    access: Access = "public"
    is_static: bool = False
    is_const: bool = False
    is_virtual: bool = False
    is_pure: bool = False
    is_template: bool = False
    is_deleted_or_default: bool = False
    internal_linkage: bool = False  # static free function or anonymous namespace
    comment: str = ""
    decl_file: str = ""
    decl_line: int = 0
    def_file: str = ""
    def_line: int = 0
    body: str = ""

    @property
    def key(self) -> str:
        return f"{self.qualified_name}/{self.param_count}"

    @property
    def is_testable(self) -> bool:
        if self.name == "main" and not self.class_name:
            return False
        if self.internal_linkage or self.access != "public":
            return False
        if self.kind == "dtor" or self.is_deleted_or_default:
            return False
        if self.is_pure and not self.body:
            return False
        return True


class ClassInfo(BaseModel):
    name: str
    qualified_name: str
    namespace: str = ""
    is_struct: bool = False
    file: str = ""
    line: int = 0
    comment: str = ""
    text: str = ""


class FileInfo(BaseModel):
    path: str
    includes: list[str] = Field(default_factory=list)


class AnalysisResult(BaseModel):
    root: str = ""
    files: list[FileInfo] = Field(default_factory=list)
    classes: list[ClassInfo] = Field(default_factory=list)
    functions: list[FunctionInfo] = Field(default_factory=list)

    def testable_functions(self) -> list[FunctionInfo]:
        return [f for f in self.functions if f.is_testable]

    def find_class(self, qualified_name: str) -> ClassInfo | None:
        for c in self.classes:
            if c.qualified_name == qualified_name:
                return c
        return None
