"""
Build XTS usage index v1.

Usage:
    python3 tests/golden/tools/build_xts_usage_index.py [xts_root] [--output path]

If xts_root is not provided, falls back to $XTS_ACTS_ROOT environment variable.
"""
from __future__ import annotations

import sys
import os
from pathlib import Path

# Ensure src is on the path when run directly
_src = Path(__file__).parents[3] / "src"
if str(_src) not in sys.path:
    sys.path.insert(0, str(_src))

from arkui_xts_selector.xts_usage_index import main

if __name__ == "__main__":
    main()
