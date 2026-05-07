"""AST-based ground-truth oracle for method-level diffs using tree-sitter C++ parsing."""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Literal

from arkui_xts_selector.tree_sitter_parsers import _get_ts_cpp_parser, _ts_extract_func_name


ChangeKind = Literal[
    "added_method",
    "removed_method",
    "signature_modified",
    "body_modified",
]


@dataclass(frozen=True)
class MethodSnapshot:
    file_path: str
    parent_class: str | None
    method_name: str
    qualified_name: str
    signature: str
    body_hash: str
    line_start: int
    line_end: int


@dataclass(frozen=True)
class MethodChange:
    file_path: str
    parent_class: str | None
    method_name: str
    qualified_name: str
    change_kind: ChangeKind
    pre: MethodSnapshot | None
    post: MethodSnapshot | None


def extract_method_changes(
    repo_root: Path,
    base_sha: str,
    head_sha: str,
    changed_files: list[str],
) -> list[MethodChange]:
    """Extract method-level changes between two git commits.

    Args:
        repo_root: Path to the git repository
        base_sha: Base commit SHA
        head_sha: Head commit SHA
        changed_files: List of changed file paths (relative to repo_root)

    Returns:
        List of MethodChange objects describing method-level changes
    """
    import subprocess

    changes: list[MethodChange] = []

    for file_path in changed_files:
        try:
            pre_content = _git_show(repo_root, base_sha, file_path)
        except subprocess.CalledProcessError:
            pre_content = None

        try:
            post_content = _git_show(repo_root, head_sha, file_path)
        except subprocess.CalledProcessError:
            post_content = None

        if file_path.endswith((".cpp", ".cc", ".cxx", ".h", ".hpp", ".hh")):
            changes.extend(_diff_cpp(file_path, pre_content, post_content))
        elif file_path.endswith(".d.ts"):
            changes.extend(_diff_dts(file_path, pre_content, post_content))
        elif file_path.endswith(".idl"):
            changes.extend(_diff_idl(file_path, pre_content, post_content))
        elif file_path.endswith((".ets", ".ts")):
            changes.extend(_diff_ets(file_path, pre_content, post_content))

        file_changes = _diff_cpp(file_path, pre_content, post_content)
        changes.extend(file_changes)

    return changes


def _git_show(repo_root: Path, sha: str, path: str) -> bytes:
    """Get file content at a specific commit using git show."""
    import subprocess

    result = subprocess.run(
        ["git", "show", f"{sha}:{path}"],
        cwd=repo_root,
        check=True,
        capture_output=True,
    )
    return result.stdout


def _diff_cpp(file_path: str, pre: bytes | None, post: bytes | None) -> list[MethodChange]:
    """Diff two C++ file contents and extract method-level changes.

    Args:
        file_path: Path to the file being diffed
        pre: Content before change (None if file was added)
        post: Content after change (None if file was deleted)

    Returns:
        List of MethodChange objects
    """
    changes: list[MethodChange] = []

    pre_methods = _parse_cpp_methods(pre, file_path) if pre else []
    post_methods = _parse_cpp_methods(post, file_path) if post else []

    pre_index = {m.qualified_name: m for m in pre_methods}
    post_index = {m.qualified_name: m for m in post_methods}

    pre_names = set(pre_index.keys())
    post_names = set(post_index.keys())

    added = post_names - pre_names
    removed = pre_names - post_names
    common = pre_names & post_names

    for name in added:
        changes.append(
            MethodChange(
                file_path=file_path,
                parent_class=post_index[name].parent_class,
                method_name=post_index[name].method_name,
                qualified_name=name,
                change_kind="added_method",
                pre=None,
                post=post_index[name],
            )
        )

    for name in removed:
        changes.append(
            MethodChange(
                file_path=file_path,
                parent_class=pre_index[name].parent_class,
                method_name=pre_index[name].method_name,
                qualified_name=name,
                change_kind="removed_method",
                pre=pre_index[name],
                post=None,
            )
        )

    for name in common:
        pre_method = pre_index[name]
        post_method = post_index[name]

        if pre_method.signature != post_method.signature:
            changes.append(
                MethodChange(
                    file_path=file_path,
                    parent_class=pre_method.parent_class,
                    method_name=pre_method.method_name,
                    qualified_name=name,
                    change_kind="signature_modified",
                    pre=pre_method,
                    post=post_method,
                )
            )
        elif pre_method.body_hash != post_method.body_hash:
            changes.append(
                MethodChange(
                    file_path=file_path,
                    parent_class=pre_method.parent_class,
                    method_name=pre_method.method_name,
                    qualified_name=name,
                    change_kind="body_modified",
                    pre=pre_method,
                    post=post_method,
                )
            )

    return changes


def _parse_cpp_methods(content: bytes, file_path: str) -> list[MethodSnapshot]:
    """Parse C++ content and extract method snapshots.

    Args:
        content: C++ source code as bytes
        file_path: Path to the file being parsed

    Returns:
        List of MethodSnapshot objects
    """
    parser, _ = _get_ts_cpp_parser()
    tree = parser.parse(content)

    methods: list[MethodSnapshot] = []
    current_class: str | None = None

    # Real C++ files (especially generated bridges) can have AST depth > 1000.
    # Bump recursion limit just for this visit; restore after.
    import sys as _sys
    _prev_limit = _sys.getrecursionlimit()
    _sys.setrecursionlimit(max(_prev_limit, 10000))

    def visit(node, class_stack: list[str]):
        nonlocal current_class

        if node.type == "class_specifier":
            class_name = None
            for child in node.children:
                if child.type == "type_identifier":
                    class_name = content[child.start_byte:child.end_byte].decode("utf-8", errors="replace")
                    break

            if class_name:
                class_stack.append(class_name)
                current_class = class_name

        elif node.type == "function_definition":
            declarator = node.child_by_field_name("declarator")
            body = node.child_by_field_name("body")

            if declarator:
                method_name, qualified_name, parent_class = _extract_cpp_name(declarator, current_class, content)

                if method_name:
                    signature = _normalize_cpp_signature(declarator, content)
                    body_hash = _hash_body(body, content) if body else ""
                    line_start = node.start_point[0] + 1
                    line_end = node.end_point[0] + 1

                    methods.append(
                        MethodSnapshot(
                            file_path=file_path,
                            parent_class=parent_class,
                            method_name=method_name,
                            qualified_name=qualified_name,
                            signature=signature,
                            body_hash=body_hash,
                            line_start=line_start,
                            line_end=line_end,
                        )
                    )

        elif node.type == "declaration":
            # Top-level declaration-only methods (void Foo();)
            func_decl = None
            for child in node.children:
                if child.type == "function_declarator":
                    func_decl = child
                    break
            if func_decl:
                method_name, qualified_name, parent_class = _extract_cpp_name(func_decl, current_class, content)
                if method_name:
                    signature = _normalize_cpp_signature(func_decl, content)
                    line_start = node.start_point[0] + 1
                    line_end = node.end_point[0] + 1
                    methods.append(
                        MethodSnapshot(
                            file_path=file_path,
                            parent_class=parent_class,
                            method_name=method_name,
                            qualified_name=qualified_name,
                            signature=signature,
                            body_hash="",
                            line_start=line_start,
                            line_end=line_end,
                        )
                    )

        elif node.type == "field_declaration":
            # Class member declarations without bodies (void Foo(); inside class)
            func_decl = None
            for child in node.children:
                if child.type == "function_declarator":
                    func_decl = child
                    break
            if func_decl:
                method_name, qualified_name, parent_class = _extract_cpp_name(func_decl, current_class, content)
                if method_name:
                    signature = _normalize_cpp_signature(func_decl, content)
                    line_start = node.start_point[0] + 1
                    line_end = node.end_point[0] + 1
                    methods.append(
                        MethodSnapshot(
                            file_path=file_path,
                            parent_class=parent_class,
                            method_name=method_name,
                            qualified_name=qualified_name,
                            signature=signature,
                            body_hash="",
                            line_start=line_start,
                            line_end=line_end,
                        )
                    )

        for child in node.children:
            visit(child, class_stack)

        if node.type == "class_specifier":
            if class_stack:
                class_stack.pop()
            current_class = class_stack[-1] if class_stack else None

    try:
        visit(tree.root_node, [])
    finally:
        _sys.setrecursionlimit(_prev_limit)
    return methods


def _hash_body(body_node, content: bytes) -> str:
    """Compute SHA256 hash of method body after stripping comments and whitespace.

    Args:
        body_node: tree-sitter node for the function body
        content: Original source code as bytes

    Returns:
        SHA256 hex digest of normalized body content
    """
    body_text = content[body_node.start_byte:body_node.end_byte]

    import re

    text = body_text.decode("utf-8", errors="replace")

    text = re.sub(r"//.*$", "", text, flags=re.MULTILINE)
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)

    text = re.sub(r"\s+", "", text)

    return sha256(text.encode("utf-8")).hexdigest()


def _normalize_cpp_signature(func_node, content: bytes) -> str:
    """Extract and normalize function signature.

    Args:
        func_node: tree-sitter function_declarator node
        content: Original source code as bytes

    Returns:
        Normalized signature string
    """
    sig_text = content[func_node.start_byte:func_node.end_byte].decode("utf-8", errors="replace")

    import re

    sig_text = re.sub(r"\s+", " ", sig_text).strip()

    return sig_text


def _extract_cpp_name(declarator_node, current_class: str | None, content: bytes = b"") -> tuple[str, str, str | None]:
    """Extract method name, qualified name, and parent class from a declarator."""
    method_name = _ts_extract_func_name(declarator_node, content)

    if not method_name:
        method_name = "unknown"

    qualified_name = method_name
    parent_class = None

    if current_class:
        qualified_name = f"{current_class}::{method_name}"
        parent_class = current_class
    else:
        for child in declarator_node.children:
            if child.type == "qualified_identifier":
                raw = content[child.start_byte:child.end_byte].decode("utf-8", errors="replace")
                if "::" in raw:
                    parts = raw.rsplit("::", 1)
                    parent_class = parts[0]
                    method_name = parts[1]
                    qualified_name = raw

    return method_name, qualified_name, parent_class


def _parse_text_signatures(content: bytes) -> dict[str, str]:
    """Extract interface/class method signatures from .d.ts/.ts text.

    Returns dict of qualified_name → signature for diffing.
    """
    import re

    text = content.decode("utf-8", errors="replace")

    # Normalize: flatten braces so each { and } is on its own logical boundary
    text = re.sub(r"\{", " {\n", text)
    text = re.sub(r"\}", "\n}\n", text)
    text = re.sub(r";", ";\n", text)

    sigs: dict[str, str] = {}
    current_iface: str | None = None

    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("//") or stripped.startswith("/*"):
            continue

        m = re.match(r"(?:export\s+)?(?:declare\s+)?(?:interface|class)\s+(\w+)", stripped)
        if m:
            current_iface = m.group(1)
            continue

        if stripped.startswith("}"):
            current_iface = None
            continue

        # Method signature: name(...): type;
        m = re.match(r"(\w+)\s*\(", stripped)
        if m and current_iface and stripped.endswith(";"):
            name = m.group(1)
            sig = re.sub(r"\s+", " ", stripped).strip().rstrip(";")
            sigs[f"{current_iface}::{name}"] = sig
            continue

        # Property: name: type;
        m = re.match(r"(?:readonly\s+)?(\w+)\s*(?:\??)\s*:\s*[^;]+;", stripped)
        if m and current_iface:
            name = m.group(1)
            sigs[f"{current_iface}::{name}"] = f"prop:{name}"

    return sigs


def _diff_signatures(
    file_path: str,
    pre: bytes | None,
    post: bytes | None,
    change_kind_sig: str = "signature_modified",
    change_kind_added: str = "added_method",
    change_kind_removed: str = "removed_method",
) -> list[MethodChange]:
    """Generic signature-based diff for .d.ts/.idl/.ts files."""
    pre_sigs = _parse_text_signatures(pre) if pre else {}
    post_sigs = _parse_text_signatures(post) if post else {}

    changes: list[MethodChange] = []

    for qname in set(post_sigs) - set(pre_sigs):
        parent, method = qname.split("::", 1) if "::" in qname else (None, qname)
        changes.append(MethodChange(
            file_path=file_path, parent_class=parent, method_name=method,
            qualified_name=qname, change_kind=change_kind_added,
            pre=None, post=None,
        ))

    for qname in set(pre_sigs) - set(post_sigs):
        parent, method = qname.split("::", 1) if "::" in qname else (None, qname)
        changes.append(MethodChange(
            file_path=file_path, parent_class=parent, method_name=method,
            qualified_name=qname, change_kind=change_kind_removed,
            pre=None, post=None,
        ))

    for qname in set(pre_sigs) & set(post_sigs):
        if pre_sigs[qname] != post_sigs[qname]:
            parent, method = qname.split("::", 1) if "::" in qname else (None, qname)
            changes.append(MethodChange(
                file_path=file_path, parent_class=parent, method_name=method,
                qualified_name=qname, change_kind=change_kind_sig,
                pre=None, post=None,
            ))

    return changes


def _diff_dts(file_path: str, pre: bytes | None, post: bytes | None) -> list[MethodChange]:
    return _diff_signatures(file_path, pre, post)


def _diff_idl(file_path: str, pre: bytes | None, post: bytes | None) -> list[MethodChange]:
    return _diff_signatures(file_path, pre, post)


def _diff_ets(file_path: str, pre: bytes | None, post: bytes | None) -> list[MethodChange]:
    return _diff_signatures(file_path, pre, post)
