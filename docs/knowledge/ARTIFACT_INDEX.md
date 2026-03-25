# Artifact Index

## Core docs
- `README.md`
- `docs/REQUIREMENTS.md`
- `docs/BENCHMARK.md`
- `docs/ARCHITECTURE.md`
- `docs/DESIGN.md`

## Working docs
- `.scratchpad/research.md`
- `.scratchpad/plan.md`
- `docs/knowledge/PROJECT_MEMORY.md`
- `docs/knowledge/ARTIFACT_INDEX.md`

## Local process artifacts
- `docs/reports/REVIEW-T-20260321-arkui-xts-selector-v1.md`
- `docs/reports/HANDOFF-T-20260321-arkui-xts-selector-v1.md`

## Reference material for evaluation
- `xts_bm.txt`
- `xts_haps.txt`
- `work.zip`

## Implementation files touched in v1
- `src/arkui_xts_selector/cli.py`
- `config/path_rules.json`
- `config/composite_mappings.json`
- `tests/test_cli_design_v1.py`

## Analysis and improvements (2026-03-21)
- `docs/reports/ANALYSIS-T-20260321-test-selection-quality.md` — critical review with examples and prioritised improvements
- `tests/test_cli_design_v1.py` — extended to 12 tests (added negative cases, boundary checks, variant fix test)
- `src/arkui_xts_selector/cli.py:resolve_variants_mode` — fixed: `components_ng/pattern/` files now resolve to `static` instead of `both`
