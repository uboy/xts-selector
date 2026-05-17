"""--explain <test_project> -- list API entities that a test project covers."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def cmd_explain(args: argparse.Namespace) -> int:
    """Execute the explain command."""
    test_project = args.test_project

    # Try to find usage signatures for this test project
    print(f"Test project: {test_project}")

    # If we have usage_extractor, use it
    try:
        from ..indexing.ets_indexer import build_ets_index
        from ..indexing.usage_extractor import extract_api_usages

        # Build ETS index from the test project directory
        test_root = Path(test_project)
        if not test_root.is_dir():
            print(f"  Error: Not a directory: {test_root}", file=sys.stderr)
            return 1

        ets_index = build_ets_index(test_root)

        print(f"  Files indexed: {len(ets_index.entries)}")
        print(f"  Total usages: {ets_index.total_usages}")
        print(f"  Errors: {len(ets_index.errors)}")

        # Group API references by test module
        by_module: dict[str, set[str]] = {}
        for entry in ets_index.entries:
            if entry.test_module not in by_module:
                by_module[entry.test_module] = set()
            by_module[entry.test_module].update(entry.api_references)

        print("\n  API coverage by module:")
        for module, apis in sorted(by_module.items()):
            print(f"    {module}:")
            for api in sorted(apis):
                print(f"      - {api}")

        if ets_index.errors:
            print("\n  Errors:")
            for error in ets_index.errors:
                print(f"    {error.file_path}: {error.error}")

        return 0

    except ImportError:
        pass

    print(
        "  (explain requires ets_indexer and usage_extractor modules — showing basic info)"
    )
    return 0
