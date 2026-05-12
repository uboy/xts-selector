# PR Annotation Cards Generator

Quick reference for generating PR annotation cards for manual labeling.

## Quick Start

```bash
# Generate cards for a quality run
./scripts/generate_pr_cards.sh --run 20260508_precision_fixes
```

## Usage

### Option 1: Using the wrapper script (recommended)

```bash
# Generate cards with default paths based on run name
./scripts/generate_pr_cards.sh --run <run_name>

# Specify custom output directory
./scripts/generate_pr_cards.sh --run 20260508_precision_fixes --output local/my_cards
```

### Option 2: Using Python directly

```bash
python3 scripts/generate_pr_cards.py \
    --candidates local/quality_runs/<run>/golden_100_candidates.json \
    --batch-results local/quality_runs/<run>/batch_results.json \
    --pr-api-cache-dir local/pr_api_cache \
    --output-dir local/golden_cards
```

## Candidates File Format

The script supports three formats:

### Format 1: Simple list
```json
[
  {"pr_number": 84269, "category": "component_api"},
  {"pr_number": 83999, "category": "test_only"}
]
```

### Format 2: By category
```json
{
  "by_category": {
    "component_api": [84269, 83246],
    "broad_infra": [84276, 84279],
    "test_only": [83999, 84414]
  }
}
```

### Format 3: Golden PR set schema
```json
{
  "golden_prs": [
    {"pr_number": 84269, "category": "component_api", "title": "...", "notes": "..."}
  ]
}
```

## Output Files

The script generates:

1. **PR Cards**: `PR_{number}_card.md` — Individual annotation cards for each PR
2. **Index**: `golden_cards_index.md` — Summary table of all PRs
3. **Template**: `golden_pr_set_template.json` — JSON template for filling in annotations

## Card Structure

Each card contains:

- **Meta**: PR URL, category, selector status, CI policy, risk, files/targets counts
- **Changed Files**: Table showing files, APIs, and unresolved status
- **Patch Hunks**: Abbreviated diffs (first 50 lines per file)
- **Selector Results**: Selected targets, canonical/affected APIs, unresolved files
- **Annotation**: Fill-in section for human reviewers

## Common Categories

- `component_api` — Changes to component implementation APIs
- `broad_infra` — Broad infrastructure changes (rendering, adapters, etc.)
- `test_only` — Test-only changes with no production impact
- `documentation` — Documentation or config-only changes

## Example Workflow

1. **Generate cards**:
   ```bash
   ./scripts/generate_pr_cards.sh --run 20260508_precision_fixes
   ```

2. **Review cards**:
   - Open `local/golden_cards/golden_cards_index.md`
   - Navigate to individual PR cards
   - Review changes and selector results

3. **Annotate each PR**:
   - Fill in `must_run` (required XTS targets)
   - Fill in `should_run` (optional targets)
   - Fill in `must_not_run` (false positives)
   - Set `expected_policy` (ok/warn/require_broader_suite/manual_review)
   - Add `notes` (observations)

4. **Populate golden set**:
   - Copy `golden_pr_set_template.json`
   - Fill in annotations from cards
   - Add PR titles (from GitCode API)
   - Save as `config/golden_pr_set.json`

## Troubleshooting

### Missing patch data
If a card shows `[patch data not cached]`:
```bash
# Re-cache the PR
python3 scripts/cache_pr_list.py \
    --pr-list https://gitcode.com/openharmony/arkui_ace_engine/merge_requests/84269 \
    --pr-api-cache-dir local/pr_api_cache
```

### PR not in batch results
Re-run batch validation for that PR:
```bash
python3 -m arkui_xts_selector validate-batch \
    --pr-list-file <pr-list> \
    --output local/quality_runs/<run>/batch_results.json \
    --pr-api-cache-dir local/pr_api_cache
```

### Wrong category assignment
Categories are derived from the candidates file. Edit the candidates file to fix:
```json
{
  "by_category": {
    "component_api": [84269],  // correct category
    "test_only": [83999]
  }
}
```

## See Also

- `local/golden_cards/README.md` — Detailed documentation for card reviewers
- `scripts/generate_pr_cards.py` — Full documentation with docstring
