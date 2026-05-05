"""--trace <file>:<symbol> -- show the full chain from a source symbol to consumer tests."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ..indexing.cpp_parser import parse_cpp_file
from ..indexing.file_role import classify
from ..indexing.sdk_indexer import build_sdk_index
from ..indexing.source_to_api import build_source_to_api_mapping
from ..indexing.ace_indexer import AceIndexResult, AceIndexEntry


def cmd_trace(args: argparse.Namespace) -> int:
    """Execute the trace command."""
    file_path, _, symbol = args.target.partition(":")

    path = Path(file_path)
    if not path.exists():
        # Try relative to repo root
        if args.repo_root:
            path = Path(args.repo_root) / file_path
    if not path.exists():
        print(f"File not found: {file_path}", file=sys.stderr)
        return 1

    # Parse C++ file
    try:
        parsed = parse_cpp_file(path)
    except Exception as exc:
        print(f"Parse error: {exc}", file=sys.stderr)
        return 1

    # Classify and resolve
    rel = str(path)
    role, family = classify(rel)

    # Build SDK index if sdk_root provided
    sdk = None
    if args.sdk_root:
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
            if sdk:
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
                mappings = build_source_to_api_mapping(synthetic_ace_index, sdk_index=sdk)
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
