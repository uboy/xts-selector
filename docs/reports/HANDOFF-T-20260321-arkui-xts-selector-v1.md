# Handoff

## Summary of changes
- Added project-level variant classification and variant-aware filtering to the selector.
- Made symbol-query and changed-file flows repo-root-aware when reading `Test.json` metadata.
- Added candidate buckets and improved compound path token handling for indirect component matches like `menu_item`.
- Tightened noisy changed-file heuristics and gated the content-modifier unresolved warning to relevant cases.
- Added unit tests covering variant filtering, repo-root-aware metadata reads, auto variant resolution, and unresolved-reason behavior.

## Files touched
- /data/home/dmazur/proj/arkui-xts-selector/src/arkui_xts_selector/cli.py
- /data/home/dmazur/proj/arkui-xts-selector/config/path_rules.json
- /data/home/dmazur/proj/arkui-xts-selector/config/composite_mappings.json
- /data/home/dmazur/proj/arkui-xts-selector/tests/test_cli_design_v1.py
- /data/home/dmazur/proj/arkui-xts-selector/.scratchpad/research.md
- /data/home/dmazur/proj/arkui-xts-selector/.scratchpad/plan.md
- /data/home/dmazur/proj/arkui-xts-selector/docs/REQUIREMENTS.md
- /data/home/dmazur/proj/arkui-xts-selector/docs/BENCHMARK.md
- /data/home/dmazur/proj/arkui-xts-selector/docs/DESIGN.md
- /data/home/dmazur/proj/arkui-xts-selector/docs/ARCHITECTURE.md

## Verification commands and results
- `python3 -m py_compile /data/home/dmazur/proj/arkui-xts-selector/src/arkui_xts_selector/cli.py /data/home/dmazur/proj/arkui-xts-selector/tests/test_cli_design_v1.py` -> passed
- `python3 -m unittest discover -s /data/home/dmazur/proj/arkui-xts-selector/tests -p 'test_*.py'` -> passed, 7 tests
- `PYTHONPATH=/data/home/dmazur/proj/arkui-xts-selector/src python3 -m arkui_xts_selector.cli --xts-root /data/home/dmazur/proj/ohos_master/test/xts/acts/arkui --sdk-api-root /data/home/dmazur/proj/ohos_master/interface/sdk-js/api --git-root /data/home/dmazur/proj/ohos_master/foundation/arkui/ace_engine --acts-out-root /data/home/dmazur/proj/out/release/suites/acts --symbol-query ButtonModifier --variants static --top-projects 1 --top-files 1 --json` -> passed
- `PYTHONPATH=/data/home/dmazur/proj/arkui-xts-selector/src python3 -m arkui_xts_selector.cli --xts-root /data/home/dmazur/proj/ohos_master/test/xts/acts/arkui --sdk-api-root /data/home/dmazur/proj/ohos_master/interface/sdk-js/api --git-root /data/home/dmazur/proj/ohos_master/foundation/arkui/ace_engine --acts-out-root /data/home/dmazur/proj/out/release/suites/acts --changed-file /data/home/dmazur/proj/ohos_master/foundation/arkui/ace_engine/frameworks/core/components_ng/pattern/menu/menu_item/menu_item_pattern.cpp --variants auto --top-projects 3 --top-files 1 --json` -> passed, effective_variants_mode=both

## Risks / blockers / follow-ups
- Ranking for indirect component files is still broad; the next improvement should prioritize component-specific modifier suites over generic common-attrs suites.
- Built artifact enrichment remains unverified in the current worktree because `/data/home/dmazur/proj/out/release/suites/acts` is missing.
- `auto` variant resolution is intentionally heuristic in v1 and will need richer evidence to distinguish shared-core changes more accurately.

Generated at: 2026-03-21T08:18:48Z
