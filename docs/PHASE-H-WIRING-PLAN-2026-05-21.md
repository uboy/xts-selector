# Phase H — Universal Pipeline Wiring Plan

Date: 2026-05-21
Goal: connect Phase A–G library to production CLI so universal-impact chain actually runs on user PRs.

## Context (read before starting any track)

- `docs/UNIVERSAL-IMPACT-RESOLUTION-DESIGN-2026-05-20.md` — chain spec.
- `docs/UNIVERSAL-IMPACT-FINAL-CLEANUP-AUDIT-2026-05-20.md` — phases A–G done as library.
- **Critical finding:** Phase A–E resolvers have **zero production callers**. Only Phase F precision is wired (`cli.py:2877-2929`) and only as advisory. Legacy lexical scorer still runs main path. `false_must_run=0` holds because new chain is dead code.

## Non-negotiable rules (every track)

- `false_must_run` must remain **0**
- `manual_verified` must remain **212**
- No direct `file→test` hardcode
- No fake exact SDK API
- No `must_run` from profile/symbol/hunk/score alone
- Graceful degradation without env vars
- No changes to 212 accepted golden cases
- Each track produces report `docs/PHASE-H-<TRACK>-REPORT-2026-05-21.md`
- Each track commits to its own branch: `feature/phase-h-<track>`
- Track lands via PR merge into `feature/selector-gap-families` (or `master` if branch already merged)

## Parallel tracks

```
Track A: compute_max_bucket unify    ─┐
Track B: broad infra profiles config ─┼─> Track E: pipeline orchestrator ─> Track F: integration harness
Track C: honesty marker model        ─┘
Track D: git diff auto-precision     (independent, can land anytime)
```

Tracks A, B, C, D run **in parallel**. E starts only when A+B+C land. F starts only when E lands.

---

## Track A — Unify `compute_max_bucket()` (blocker #2)

**Branch:** `feature/phase-h-bucket-unify`
**Agent type:** `implementation-developer`
**Effort:** small (~1 day)
**Risk:** low (covered by existing tests)

### Problem

Phase C created `consumer_usage_linker.compute_max_bucket()` (line 284). Four Phase B resolvers still have local `_compute_max_bucket()` with `# TODO(Phase E)` divergence comments:
- `src/arkui_xts_selector/impact/gesture_api_resolver.py:607`
- `src/arkui_xts_selector/impact/native_peer_resolver.py:453`
- `src/arkui_xts_selector/impact/ani_bridge_resolver.py:418`
- `src/arkui_xts_selector/impact/native_event_resolver.py:448`

Local copies take `base_max_bucket` + check `edge.confidence in ("strong","medium")`. Shared takes `impact_topics, sdk_topics, usage_edges`.

### Tasks

1. Read shared `compute_max_bucket()` signature and behavior.
2. Read each local `_compute_max_bucket()`; document semantic differences in track report.
3. Extend shared function (if needed) to subsume local checks, OR refactor each resolver call-site to pass right arguments.
4. Replace all 4 local methods with `from .consumer_usage_linker import compute_max_bucket`.
5. Delete `# TODO(Phase E)` comments.
6. Add `tests/test_bucket_parity.py`: for each resolver, build representative result with/without env, assert `compute_max_bucket(shared)` returns same bucket as old `_compute_max_bucket(local)` would have.
7. Run targeted suite:
   ```
   python3 -m pytest tests/test_gesture_api_resolver.py tests/test_native_peer_resolver.py tests/test_ani_bridge_resolver.py tests/test_native_event_resolver.py tests/test_bucket_policy_no_drift.py tests/test_bucket_parity.py -q
   make validate-fast validate-graph validate-universal-impact
   ```
8. Commit `feat(phase-h-a): unify compute_max_bucket across resolvers`.

### Acceptance

- All 4 resolvers import shared `compute_max_bucket`.
- No `_compute_max_bucket` method remains in resolver classes.
- `tests/test_bucket_parity.py` asserts parity ≥ 12 cases.
- No regression in Phase B/C/D/E/F tests.
- `false_must_run=0`, `manual_verified=212`.

---

## Track B — Broad infra profiles for top-pain files (blocker #4)

**Branch:** `feature/phase-h-broad-profiles`
**Agent type:** `implementation-developer`
**Effort:** small (~0.5 day)
**Risk:** low (config-only + tests)

### Problem

User-named broad files have NO source_layer rule AND NO infra_profile match:
- `view_abstract.cpp` — cross-component property setter
- `frame_node.cpp` — base node every UI component inherits
- `pipeline_context.cpp` — global render pipeline

Legacy lexical scorer over-resolves these. Universal pipeline (once wired) would classify `layer=unknown` and emit nothing. Both bad.

### Tasks

1. Read `config/source_layers.json`, `config/infra_profiles.json`, `config/broad_infrastructure_files.json` (legacy reference).
2. Add 3 source_layer rules in `config/source_layers.json`:
   - `view_abstract_infra` → layer `component_universal`
   - `frame_node_infra` → layer `node_universal`
   - `pipeline_context_infra` → layer `pipeline_universal`
   (Add the 3 new layer values to `SourceLayer` Literal in `src/arkui_xts_selector/impact/models.py`.)
3. Add 3 entries to `config/infra_profiles.json`:
   - `component_universal_profile` (source_layers: `component_universal`; broad surface; max_bucket `recommended`; target_policy `bounded_smoke`; query terms cover Button/Text/Image/Column/Row component smoke).
   - `node_universal_profile` (source_layers: `node_universal`; risk: any FrameNode-derived component; query terms include component lifecycle smoke).
   - `pipeline_universal_profile` (source_layers: `pipeline_universal`; risk: rendering pipeline; query terms include rendering/layout/measure smoke).
4. Each profile MUST include `"description": "..., bounded smoke only — exact SDK API cannot be inferred"`.
5. Add tests `tests/test_broad_infra_profile_resolver_top_files.py`:
   - `view_abstract.cpp` classified as `component_universal` and matches `component_universal_profile`
   - `frame_node.cpp` classified as `node_universal` and matches `node_universal_profile`
   - `pipeline_context.cpp` classified as `pipeline_universal` and matches `pipeline_universal_profile`
   - None emit exact SDK API
   - None emit `must_run`
6. Run:
   ```
   python3 -m pytest tests/test_source_classifier.py tests/test_broad_infra_profile_resolver.py tests/test_broad_infra_profile_resolver_top_files.py -q
   make validate-fast validate-graph validate-universal-impact
   ```
7. Commit `feat(phase-h-b): add broad infra profiles for view_abstract/frame_node/pipeline_context`.

### Acceptance

- 3 new layers in `SourceLayer` literal.
- 3 new source_layer rules.
- 3 new infra profiles.
- 5 new tests pass.
- `false_must_run=0`, `manual_verified=212`.

---

## Track C — Honesty marker model (blocker #3)

**Branch:** `feature/phase-h-honesty-marker`
**Agent type:** `implementation-developer`
**Effort:** small (~1 day)
**Risk:** low (additive output field)

### Problem

User principle: "лучше если скрипт выдаст чуть больше тестов и АПИ, но честно напишет что определил он их поверхностно". Currently:
- `SourceImpactEntity.confidence` exists but isn't surfaced.
- `_LAYER_LIMITATIONS["unknown"]` strings exist but aren't surfaced.
- CLI report has no `resolution_confidence` field.

### Tasks

1. Add model `src/arkui_xts_selector/impact/resolution_confidence.py`:
   ```python
   @dataclass(frozen=True)
   class ResolutionConfidence:
       level: str  # "deep" | "shallow" | "unresolved"
       shallow_files: tuple[str, ...]
       unresolved_files: tuple[str, ...]
       reasons: tuple[str, ...]
       affects_must_run: bool  # False — never affects bucket, advisory only
       human_summary: str
   ```
2. Add classifier `compute_resolution_confidence(entities, profile_matches, topic_matches) -> ResolutionConfidence`:
   - `level="deep"` only if **all** files have layer ≠ unknown AND ≥1 topic match (not just profile).
   - `level="shallow"` if any file matches only an infra_profile OR has `confidence in {"low","medium"}`.
   - `level="unresolved"` if any file is `layer=unknown` AND no profile matches.
3. Output JSON shape (additive):
   ```json
   "resolution_confidence": {
     "level": "shallow",
     "shallow_files": ["view_abstract.cpp"],
     "unresolved_files": [],
     "reasons": ["view_abstract.cpp matched only component_universal_profile — bounded smoke only"],
     "human_summary": "1 of 3 files resolved at profile level — please review profile_targets manually"
   }
   ```
4. Add `tests/test_resolution_confidence.py` — 8 tests covering deep/shallow/unresolved transitions.
5. NO CLI wiring here — that's Track E. Track C delivers the model + computation only.
6. Run:
   ```
   python3 -m pytest tests/test_resolution_confidence.py -q
   make validate-fast validate-graph validate-universal-impact
   ```
7. Commit `feat(phase-h-c): add resolution confidence honesty marker model`.

### Acceptance

- `ResolutionConfidence` dataclass exists.
- `compute_resolution_confidence()` function works on synthetic inputs.
- 8 tests pass.
- `affects_must_run=False` — confidence is advisory, never gates bucket.
- `false_must_run=0`, `manual_verified=212`.

---

## Track D — Git diff auto-precision (high #6)

**Branch:** `feature/phase-h-diff-precision`
**Agent type:** `implementation-developer`
**Effort:** medium (~1.5 days)
**Risk:** low (additive CLI feature)

### Problem

Phase F adds `--changed-symbol` and `--changed-lines` but user must pass them manually. In CI/PR context unusable without auto-derivation from `git diff`.

### Tasks

1. Read `src/arkui_xts_selector/impact/precision_entrypoint.py` and `precision_resolver.py`.
2. Add `src/arkui_xts_selector/impact/diff_precision_extractor.py`:
   ```python
   def extract_precision_from_git_diff(base_rev: str, head_rev: str = "HEAD", repo_path: str = ".") -> list[dict]:
       """Return [{path, changed_lines: [(start,end)], changed_symbols: [str]}, ...]"""
   ```
3. Implementation: run `git diff --unified=0 base..head`, parse hunk headers (`@@ -a,b +c,d @@`), extract line ranges. For each hunk, run `SymbolSpanIndex.find_touched_symbols()` to derive symbols.
4. Add CLI flag `--from-git-diff BASE_REV` to existing CLI args. When set:
   - call `extract_precision_from_git_diff(base_rev)`
   - for each file, invoke `PrecisionResolver.resolve_changed_lines()` per hunk
   - merge results into existing `precision_evidence` output block
5. Tests `tests/test_diff_precision_extractor.py`:
   - given staged test repo with known hunks → extracts correct line ranges
   - given hunks inside known symbol → returns symbol set
   - given non-existent ref → graceful error, no crash
   - git not available → graceful degradation, returns empty + `git_unavailable` reason
6. Tests `tests/test_cli_from_git_diff.py`:
   - CLI with `--from-git-diff` flag produces `precision_evidence` from real diff
   - CLI without flag → unchanged behavior
7. Run:
   ```
   python3 -m pytest tests/test_diff_precision_extractor.py tests/test_cli_from_git_diff.py tests/test_precision_resolver.py tests/test_changed_lines_cli_precision.py -q
   make validate-fast validate-graph validate-universal-impact
   ```
8. Commit `feat(phase-h-d): auto-derive precision evidence from git diff`.

### Acceptance

- `--from-git-diff REV` flag works.
- Extracts hunks + symbols from real git diff.
- Graceful degradation: missing git/ref → reason, no crash.
- 8+ new tests pass.
- `false_must_run=0`, `manual_verified=212`.

---

## Track E — Universal pipeline orchestrator (blocker #1) — START AFTER A+B+C

**Branch:** `feature/phase-h-pipeline-orchestrator`
**Agent type:** `implementation-developer`
**Effort:** large (~2-3 days)
**Risk:** medium (changes CLI output shape — additive only)

### Problem

No top-level function wires `SourceClassifier → topic resolvers → SDK validator → ConsumerUsageLinker → BroadInfraProfileResolver → FanoutLimiter` per changed file. Each resolver has zero production callers.

### Tasks

1. Pre-req check: Tracks A, B, C must be merged. Verify:
   ```
   git log --oneline | grep -E "phase-h-(a|b|c)"
   ```
2. Read `src/arkui_xts_selector/cli.py` fully. Identify integration point near `cli.py:2870` where Phase F precision is wired.
3. Create `src/arkui_xts_selector/impact/universal_pipeline.py`:
   ```python
   class UniversalImpactPipeline:
       def __init__(self, sdk_root=None, xts_root=None, ace_engine_root=None): ...
       def run(self, changed_files: list[str]) -> dict:
           """Returns:
           {
             "per_file": [{path, source_entity, impact_topics, sdk_topics,
                          consumer_edges, infra_profile, fanout_result, max_bucket}, ...],
             "resolution_confidence": ResolutionConfidence,
             "universal_max_bucket": str,
             "warnings": list[str]
           }
           """
   ```
4. Dispatcher logic per file:
   - `entity = SourceClassifier().classify(path)`
   - If `entity.layer` in gesture domain → `GestureApiResolver(...).resolve(entity)`
   - elif native_peer → `NativePeerResolver(...).resolve(entity)`
   - elif ani_bridge → `AniBridgeResolver(...).resolve(entity)`
   - elif native_event → `NativeEventResolver(...).resolve(entity)`
   - elif jsi_bridge/inspector/select_overlay/component_universal/node_universal/pipeline_universal → `BroadInfraProfileResolver(...).resolve(entity)`
   - else → emit entity with `layer=unknown`, contribute to `unresolved_files`
5. After per-file pass: aggregate all `TargetCandidate`s into single list, run `FanoutLimiter.limit(candidates)`.
6. Call `compute_resolution_confidence(entities, profiles, topics)` for honesty marker.
7. Wire into `cli.py`:
   - new block after legacy report build, **additive only** — set `report["universal_impact"] = pipeline.run(changed_files).to_dict()`
   - set `report["resolution_confidence"] = ...`
   - Do NOT change existing keys.
   - Behind opt-in flag `--universal-impact` initially (default off). Enable by default once Track F passes.
8. Tests `tests/test_universal_pipeline.py`:
   - empty input → empty result
   - single gesture file → routes to gesture resolver
   - single broad infra file → routes to profile resolver
   - mixed files → all resolved + aggregate fanout
   - graceful degradation without env → confidence marker, no crash
   - `false_must_run=0` from pipeline output
9. Tests `tests/test_cli_universal_impact_flag.py`:
   - `--universal-impact` adds new keys
   - without flag → legacy output unchanged (byte-equal for sample PR)
10. Run:
    ```
    python3 -m pytest tests/test_universal_pipeline.py tests/test_cli_universal_impact_flag.py -q
    python3 -m pytest tests/test_pr_benchmark_acceptance_metrics.py -q
    make validate-fast validate-graph validate-universal-impact validate-pr-benchmark
    ```
11. Commit `feat(phase-h-e): wire universal-impact pipeline into CLI`.

### Acceptance

- `UniversalImpactPipeline` class with `run()` method works.
- CLI `--universal-impact` flag adds `universal_impact` + `resolution_confidence` to report.
- Without flag, legacy output byte-equal (regression test).
- Routes all 13 source layers correctly.
- `false_must_run=0` enforced inside pipeline.
- `manual_verified=212` unchanged.

---

## Track F — Joint integration harness (blocker #5) — START AFTER E

**Branch:** `feature/phase-h-joint-integration`
**Agent type:** `implementation-developer`
**Effort:** medium (~1.5 days)
**Risk:** medium (forensic — may surface real bugs)

### Problem

Headline metric `false_must_run=0` currently means "nothing in new chain emits must_run" — trivially true because chain is dead. Real metric needed: `false_must_run=0` **AND** `under_resolution=0` jointly across both legacy and universal pipelines, on real PR fixtures.

### Tasks

1. Pre-req: Track E merged.
2. Add `tests/test_joint_pipeline_integration.py`:
   - For each of 7 PR fixtures (`tests/fixtures/pr_benchmarks/*.json`):
     - Run CLI legacy path → record `must_run`, `recommended`, `affected_api_entities`.
     - Run CLI with `--universal-impact` → record same + `universal_impact.universal_max_bucket`, `resolution_confidence.level`.
     - Assert `false_must_run=0` from BOTH outputs.
     - Assert `universal_max_bucket != "must_run"` unless `legacy.must_run` is non-empty AND universal has SDK + non-import XTS edge.
     - Assert per-PR `resolution_confidence.level` matches expected (e.g. PR !84287 gesture → `deep`; PR !83746 jsi → `shallow`).
3. Add `tests/test_no_under_resolution.py`:
   - For each PR fixture, ensure either:
     - universal pipeline produces topics/profile, OR
     - `resolution_confidence.level == "unresolved"` (explicit honesty marker)
   - NEVER: empty output with no honesty marker.
4. Add `tests/test_pr_84287_pipeline_parity.py` — single deep-dive: run gesture PR through full pipeline, snapshot expected outputs, fail on drift.
5. Add new Makefile target `validate-joint-integration`:
   ```makefile
   validate-joint-integration:
       PYTHONPATH=src python3 -m pytest \
         tests/test_joint_pipeline_integration.py \
         tests/test_no_under_resolution.py \
         tests/test_pr_84287_pipeline_parity.py \
         -q
   ```
6. Add `validate-joint-integration` to `validate-all-local` chain.
7. Add CI job for `validate-joint-integration` in `.github/workflows/ci.yml`.
8. Run full validation:
   ```
   make validate-fast validate-graph validate-universal-impact validate-pr-benchmark validate-joint-integration validate-all-local
   ```
9. Document gaps surfaced (if any) in `docs/PHASE-H-F-REPORT-2026-05-21.md`. If real bugs found, file as follow-up tasks — do NOT silently fix without commit annotation.
10. Commit `test(phase-h-f): add joint pipeline integration harness`.

### Acceptance

- 3 new test files, all pass.
- `make validate-joint-integration` works.
- CI job added.
- 7 PR fixtures pass joint assertions.
- Any bugs found documented in track report; not silently fixed.
- `false_must_run=0`, `manual_verified=212`.

---

## Coordination

### Synchronization

- After A, B, C land: trigger Track E.
- After E lands: trigger Track F.
- D is independent — can land anywhere.

### Conflict zones

- Track A modifies `src/arkui_xts_selector/impact/{gesture,native_peer,ani_bridge,native_event}_resolver.py`.
- Track B modifies `src/arkui_xts_selector/impact/models.py` and `config/*.json`.
- Track C adds `src/arkui_xts_selector/impact/resolution_confidence.py` — new file, no conflict.
- Track D adds `src/arkui_xts_selector/impact/diff_precision_extractor.py` + CLI args — minor `cli.py` arg-parser edit.
- Track E touches `src/arkui_xts_selector/cli.py` around `cli.py:2870` AND adds `universal_pipeline.py`.
- Track F adds tests + Makefile + CI workflow.

**Highest risk:** Track A + Track E may both touch resolver `__init__` if E needs to instantiate them. Resolve by: A lands first, E rebuilds against A's clean signatures.

### Each track must produce

1. `docs/PHASE-H-<TRACK>-REPORT-2026-05-21.md` with:
   - what changed
   - test count before/after
   - validation results (all lanes)
   - `manual_verified`, `generated_candidate`, `needs_review`, `false_must_run`
   - GREEN/YELLOW/RED verdict
2. Single commit per track on its branch.
3. Push branch to `origin` for review.

### Final integration commit

After all 6 tracks land:
- Run `make validate-all-local validate-joint-integration`.
- Update `docs/UNIVERSAL-IMPACT-FINAL-ACCEPTANCE-2026-05-20.md` → mark Phase H complete.
- Update `docs/AGENT-RULES.md` → add Phase H to roadmap table.
- Squash-merge feature branch into master.

---

## Quick-start command for agent operator

For each track, spawn an `implementation-developer` agent with:

```
Follow CLAUDE.md and docs/AGENT-RULES.md.
Read docs/PHASE-H-WIRING-PLAN-2026-05-21.md fully.
Execute Track <X> exactly as specified.
Do not deviate from acceptance criteria.
Do not start dependent tracks.
Report when committed and pushed.
```

Tracks A, B, C, D can be spawned **simultaneously** (parallel agents).
Track E spawned only after A, B, C report done.
Track F spawned only after E reports done.
