.PHONY: validate-collect validate-fast validate-golden validate-graph validate-full validate-measurement validate-env validate-nightly validate-real-env graph-stats help

help:
	@echo "Validation targets:"
	@echo "  validate-env         - check required environment variables (roots must exist)"
	@echo "  validate-collect     - collect only, 0 errors required"
	@echo "  validate-fast        - collect + targeted unit tests (merge gate, STRICT)"
	@echo "  validate-golden      - golden schema + manual validation (merge gate, requires env)"
	@echo "  validate-graph       - graph/usage/coverage tests (STRICT)"
	@echo "  validate-full        - full pytest (tree_sitter optional deps skip)"
	@echo "  validate-measurement - broad-infra measurement-only (non-blocking)"
	@echo "  validate-nightly     - full nightly profile: fast+graph (strict) + golden+measurement (env-gated, non-blocking)"
	@echo "  validate-real-env    - like validate-golden but hard-fails on missing env"
	@echo "  graph-stats          - report collected/manual_verified/needs_review counts (best-effort)"
	@echo ""
	@echo "Failure policy:"
	@echo "  STRICT (exit 1): false_must_run > 0, collection errors, fast/graph test failures"
	@echo "  NON-BLOCKING:    measurement timeouts, golden env missing"

validate-collect:
	python3 -m pytest --collect-only -q

validate-fast:
	PYTHONPATH=src python3 -m pytest tests/test_gap_family_resolution.py tests/test_api_lineage.py tests/test_file_role.py tests/test_family_alias.py tests/test_gate_adapter.py tests/test_structured_api_details.py tests/test_bucket_gate_policy.py tests/test_coverage_equivalence.py tests/test_report_ux_evidence.py -q

validate-env:
	bash scripts/check_env.sh

validate-golden: validate-env
	python3 -m pytest tests/golden/test_golden_cases.py -q
	python3 tests/golden/tools/run_manual_golden_validation.py

validate-graph:
	PYTHONPATH=src python3 -m pytest tests/test_graph_api_symbol_modes.py tests/test_graph_validation.py tests/test_xts_usage_index.py tests/test_xts_usage_graph_link.py -q

validate-full:
	PYTHONPATH=src python3 -m pytest -q

validate-measurement:
	@echo "Running broad-infra measurement (non-blocking, may timeout)"
	python3 tests/golden/tools/run_manual_golden_validation.py || true

# ---------------------------------------------------------------------------
# Nightly profile
# Strict gate: validate-fast + validate-graph (exit 1 on failure).
# Env-gated golden: runs only if env roots are present; skips gracefully otherwise.
# Measurement: always non-blocking (|| true).
# false_must_run enforcement is embedded in validate-fast/validate-graph tests.
# ---------------------------------------------------------------------------
validate-nightly: validate-fast validate-graph
	@echo ""
	@echo "=== validate-nightly: strict gates passed ==="
	@echo "--- Running env check (non-blocking for nightly golden) ---"
	@bash scripts/check_env.sh && \
	  ( echo "--- Env OK: running validate-golden ---" && \
	    python3 -m pytest tests/golden/test_golden_cases.py -q && \
	    python3 tests/golden/tools/run_manual_golden_validation.py ) || \
	  echo "SKIP: env roots missing or incomplete — golden validation skipped (non-blocking)"
	@echo "--- Running validate-measurement (non-blocking) ---"
	@python3 tests/golden/tools/run_manual_golden_validation.py 2>&1 | tail -5 || true
	@echo "=== validate-nightly: complete ==="

# Hard-fail if env missing; then run full golden suite.
validate-real-env:
	@echo "=== validate-real-env: checking environment (hard-fail if missing) ==="
	bash scripts/check_env.sh
	@echo "--- Env OK: running golden validation ---"
	python3 -m pytest tests/golden/test_golden_cases.py -q
	python3 tests/golden/tools/run_manual_golden_validation.py
	@echo "=== validate-real-env: complete ==="

# Best-effort stats: collected tests, manual_verified, needs_review.
graph-stats:
	@echo "=== graph-stats (best-effort) ==="
	@python3 -m pytest --collect-only -q 2>/dev/null | tail -3 || true
	@python3 -c "\
import json, pathlib; \
seed = pathlib.Path('tests/golden/golden_cases_seed.json'); \
data = json.loads(seed.read_text()) if seed.exists() else {'cases': []}; \
cases = data.get('cases', []); \
mv = sum(1 for c in cases if c.get('status') == 'manual_verified'); \
nr = sum(1 for c in cases if c.get('status') == 'needs_review'); \
total = len(cases); \
print(f'Golden seed: {total} total, {mv} manual_verified, {nr} needs_review') \
" 2>/dev/null || echo "graph-stats: could not parse golden seed"
	@echo "=== graph-stats: complete (non-blocking) ==="
