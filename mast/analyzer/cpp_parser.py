"""Extract classes and functions from C++ sources with tree-sitter."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import tree_sitter_cpp
from tree_sitter import Language, Node, Parser

from .models import ClassInfo, FileInfo, FunctionInfo

_LANG = Language(tree_sitter_cpp.language())
_PARSER = Parser(_LANG)

_DECLARATOR_WRAPPERS = {
    "pointer_declarator",
    "reference_declarator",
    "parenthesized_declarator",
    "attributed_declarator",
}


def read_source(path: Path) -> str:
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "cp949", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _text(node: Node | None) -> str:
    return node.text.decode("utf-8", errors="replace") if node is not None else ""


def _find_function_declarator(node: Node | None) -> Node | None:
    while node is not None:
        if node.type == "function_declarator":
            return node
        if node.type in _DECLARATOR_WRAPPERS:
            node = node.child_by_field_name("declarator") or next(
                (c for c in node.named_children if c.type.endswith("declarator")), None
            )
            continue
        return None
    return None


def _leading_comment(node: Node) -> str:
    lines: list[str] = []
    prev = node.prev_named_sibling
    end_row = node.start_point[0]
    while prev is not None and prev.type == "comment" and end_row - prev.end_point[0] <= 1:
        lines.insert(0, _text(prev))
        end_row = prev.start_point[0]
        prev = prev.prev_named_sibling
    return "\n".join(lines)


@dataclass
class _Scope:
    namespaces: list[str] = field(default_factory=list)
    classes: list[str] = field(default_factory=list)
    anonymous: bool = False

    def prefix(self) -> str:
        return "::".join(self.namespaces + self.classes)


class CppFileParser:
    def __init__(self, path: Path, rel: str):
        self.path = path
        self.rel = rel
        self.source = read_source(path)
        self._bytes = self.source.encode("utf-8")
        self.tree = _PARSER.parse(self._bytes)
        self.classes: list[ClassInfo] = []
        self.functions: list[FunctionInfo] = []
        self.includes: list[str] = []

    def parse(self) -> FileInfo:
        self._walk_block(self.tree.root_node, _Scope())
        return FileInfo(path=self.rel, includes=self.includes)

    # -- traversal -------------------------------------------------------
    def _walk_block(self, node: Node, scope: _Scope, access: str | None = None) -> None:
        current_access = access
        for child in node.children:
            t = child.type
            if t == "preproc_include":
                self.includes.append(_text(child.child_by_field_name("path")).strip('<>"'))
            elif t in ("preproc_if", "preproc_ifdef", "preproc_else", "preproc_elif", "linkage_specification"):
                body = child.child_by_field_name("body") if t == "linkage_specification" else child
                if body is not None:
                    self._walk_block(body, scope, current_access)
            elif t == "declaration_list":
                self._walk_block(child, scope, current_access)
            elif t == "namespace_definition":
                name = _text(child.child_by_field_name("name"))
                body = child.child_by_field_name("body")
                if body is None:
                    continue
                inner = _Scope(
                    namespaces=scope.namespaces + ([n for n in name.split("::") if n] if name else []),
                    classes=list(scope.classes),
                    anonymous=scope.anonymous or not name,
                )
                self._walk_block(body, inner)
            elif t == "access_specifier":
                current_access = _text(child).strip()
            elif t in ("class_specifier", "struct_specifier"):
                self._handle_class(child, scope)
            elif t == "template_declaration":
                self._handle_template(child, scope, current_access)
            elif t in ("function_definition", "declaration", "field_declaration"):
                spec = next((c for c in child.children if c.type in ("class_specifier", "struct_specifier")), None)
                if spec is not None and spec.child_by_field_name("body") is not None:
                    self._handle_class(spec, scope)
                self._handle_function(child, scope, current_access, is_template=False)

    def _handle_template(self, node: Node, scope: _Scope, access: str | None) -> None:
        for child in node.named_children:
            if child.type in ("function_definition", "declaration", "field_declaration"):
                self._handle_function(child, scope, access, is_template=True)
            elif child.type in ("class_specifier", "struct_specifier"):
                self._handle_class(child, scope)

    def _handle_class(self, node: Node, scope: _Scope) -> None:
        name = _text(node.child_by_field_name("name"))
        body = node.child_by_field_name("body")
        if not name or body is None:
            return
        is_struct = node.type == "struct_specifier"
        anchor = node.parent if node.parent is not None and node.parent.type != "translation_unit" else node
        qualified = "::".join([p for p in (scope.prefix(), name) if p])
        self.classes.append(
            ClassInfo(
                name=name,
                qualified_name=qualified,
                namespace="::".join(scope.namespaces),
                is_struct=is_struct,
                file=self.rel,
                line=node.start_point[0] + 1,
                comment=_leading_comment(anchor if anchor.type != "declaration_list" else node),
                text=_text(node),
            )
        )
        inner = _Scope(scope.namespaces, scope.classes + [name], scope.anonymous)
        self._walk_block(body, inner, "public" if is_struct else "private")

    def _handle_function(self, node: Node, scope: _Scope, access: str | None, is_template: bool) -> None:
        fdecl = _find_function_declarator(node.child_by_field_name("declarator"))
        if fdecl is None:
            return
        name_node = fdecl.child_by_field_name("declarator")
        raw_name = _text(name_node)
        params_node = fdecl.child_by_field_name("parameters")
        params = _text(params_node) or "()"
        param_count = sum(
            1
            for p in (params_node.named_children if params_node is not None else [])
            if p.type in ("parameter_declaration", "optional_parameter_declaration", "variadic_parameter_declaration")
        )
        if params.replace(" ", "") == "(void)":
            param_count = 0

        parts = [p for p in raw_name.split("::") if p]
        if not parts:
            return
        name = parts[-1]
        owner_parts = scope.classes + parts[:-1]
        class_name = owner_parts[-1] if owner_parts else ""
        qualified = "::".join(scope.namespaces + owner_parts + [name])

        specifiers = {_text(c) for c in node.children if c.type in ("storage_class_specifier", "virtual")}
        specifiers |= {_text(c) for c in node.children if c.type == "virtual_function_specifier"}
        decl_quals = {_text(c) for c in fdecl.children if c.type == "type_qualifier"}
        is_definition = node.type == "function_definition"
        body_node = node.child_by_field_name("body")
        default_value = node.child_by_field_name("default_value")
        is_pure = default_value is not None and _text(default_value) == "0"
        is_del_def = any(c.type in ("default_method_clause", "delete_method_clause") for c in node.children)

        if name.startswith("~"):
            kind = "dtor"
        elif name.startswith("operator"):
            kind = "operator"
        elif class_name and name == class_name:
            kind = "ctor"
        elif class_name:
            kind = "method"
        else:
            kind = "free"

        return_type = _text(node.child_by_field_name("type"))
        # pointer/reference return types live on wrapping declarators
        outer = node.child_by_field_name("declarator")
        if outer is not None and outer.type in ("pointer_declarator", "reference_declarator"):
            return_type += "*" if outer.type == "pointer_declarator" else "&"

        header_end = body_node.start_byte if body_node is not None else node.end_byte
        signature = self._bytes[node.start_byte : header_end].decode("utf-8", "replace").strip()
        signature = signature.rstrip(";").strip()

        is_member_decl = bool(scope.classes)
        fn = FunctionInfo(
            name=name,
            qualified_name=qualified,
            namespace="::".join(scope.namespaces),
            class_name=class_name,
            kind=kind,
            return_type=return_type,
            parameters=params,
            param_count=param_count,
            signature=" ".join(signature.split()),
            access=(access or "public") if is_member_decl else "public",
            is_static="static" in specifiers,
            is_const="const" in decl_quals,
            is_virtual="virtual" in specifiers,
            is_pure=is_pure,
            is_template=is_template,
            is_deleted_or_default=is_del_def,
            internal_linkage=scope.anonymous or ("static" in specifiers and not class_name),
            comment=_leading_comment(node.parent if node.parent is not None and node.parent.type == "template_declaration" else node),
            decl_file=self.rel,
            decl_line=node.start_point[0] + 1,
        )
        if is_definition and body_node is not None:
            fn.def_file = self.rel
            fn.def_line = node.start_point[0] + 1
            fn.body = _text(node)
        self.functions.append(fn)
