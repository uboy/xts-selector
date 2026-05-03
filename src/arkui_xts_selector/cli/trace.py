"""--trace <file>:<symbol> -- show the full chain from a source symbol to consumer tests."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def cmd_trace(args: argparse.Namespace) -> int:
    """Execute the trace command."""
    file_path, _, symbol = args.target.partition(":")

    # Try to import optional Phase 2/3 modules
    try:
        from ..indexing.cpp_parser import parse_cpp_file
        _has_cpp_parser = True
    except ImportError:
        _has_cpp_parser = False
        print("Note: C++ parser not available - showing basic file info only", file=sys.stderr)

    try:
        from ..indexing.file_role import classify
        _has_file_role = True
    except ImportError:
        _has_file_role = False

    try:
        from ..indexing.sdk_indexer import build_sdk_index
    except ImportError:
        build_sdk_index = None

    try:
        from ..indexing.source_to_api import build_source_to_api_mapping
    except ImportError:
        build_source_to_api_mapping = None

    try:
        from ..indexing.ace_indexer import AceIndexResult, AceIndexEntry
    except ImportError:
        AceIndexResult = None
        AceIndexEntry = None

    path = Path(file_path)
    if not path.exists():
        # Try relative to repo root
        if args.repo_root:
            path = Path(args.repo_root) / file_path
    if not path.exists():
        print(f"File not found: {file_path}", file=sys.stderr)
        return 1

    # Parse C++ file if parser is available
    if _has_cpp_parser:
        try:
            parsed = parse_cpp_file(path)
        except Exception as exc:
            print(f"Parse error: {exc}", file=sys.stderr)
            return 1
    else:
        # No parser available - just show file info
        print(f"{file_path}")
        print(f"  └─ C++ parser not available (Phase 2 modules not installed)")
        return 0

    # Classify and resolve
    rel = str(path)
    role = "unknown"
    family = None
    if _has_file_role:
        role, family = classify(rel)

    # Build SDK index if sdk_root provided
    sdk = None
    if args.sdk_root and build_sdk_index:
        try:
            sdk = build_sdk_index(Path(args.sdk_root))
        except Exception as exc:
            print(f"SDK index build failed: {exc}", file=sys.stderr)

    # Find matching methods
    found = False
    for cls in parsed.classes:
        for m in cls.methods:
            if symbol and symbol not in m.name and symbol not in (m.qualified or ""):
                continue
            print(f"{file_path}:{m.line}")
            print(f"  └─ method {m.qualified or m.name} [span {m.line}-{m.end_line}]")
            print(f"     └─ role={role}, family={family}")
            if sdk and build_source_to_api_mapping and AceIndexEntry and AceIndexResult:
                # Build synthetic AceIndexResult from the parsed file
                synthetic_entry = AceIndexEntry(
                    file_path=str(path),
                    role=role,
                    family=family,
                    classes=(cls,),
                    free_functions=parsed.free_functions,
                    includes=parsed.includes,
                )
                synthetic_ace_index = AceIndexResult(entries=(synthetic_entry,))
                mappings = build_source_to_api_mapping(synthetic_ace_index)
                for mapping in mappings:
                    if symbol and symbol not in mapping.source_qualified and symbol not in mapping.api_public_name:
                        continue
                    print(f"        └─ {mapping.confidence} → {mapping.api_public_name}")
            found = True

    # Also check free functions
    for func_name in parsed.free_functions:
        if symbol and symbol not in func_name:
            continue
        print(f"{file_path}:<free>")
        print(f"  └─ function {func_name}")
        print(f"     └─ role={role}, family={family}")
        found = True

    if not found:
        print(f"No matching methods for '{symbol}' in {file_path}", file=sys.stderr)
        return 1
    return 0
