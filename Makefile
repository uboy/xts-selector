.PHONY: validate-collect validate-fast validate-golden validate-graph validate-full validate-measurement validate-env help

help:
	@echo "Validation targets:"
	@echo "  validate-env         - check required environment variables (roots must exist)"
	@echo "  validate-collect     - collect only, 0 errors required"
	@echo "  validate-fast        - collect + targeted unit tests (merge gate)"
	@echo "  validate-golden      - golden schema + manual validation (merge gate, requires env)"
	@echo "  validate-graph       - graph/usage/coverage tests"
	@echo "  validate-full        - full pytest (tree_sitter optional deps skip)"
	@echo "  validate-measurement - broad-infra measurement-only (non-blocking)"

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
