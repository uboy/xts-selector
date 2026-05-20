# arkui-xts-selector agent rules

> Canonical reference for all agents and prompts.
> CLAUDE.md points here. Command files reference this document.
> Do not duplicate these rules in individual prompts — just say "follow AGENT-RULES.md".

---

## Project purpose

Select the minimal sufficient XTS regression set for `arkui_ace_engine` changes.

Correct resolution chain:

```
ChangedInput
→ SourceImpactEntity   (Phase A)
→ ImpactTopic          (Phase B resolvers)
→ SdkApiTopic          (Phase B SDK validation)
→ ConsumerUsageEdge    (Phase B/C XTS usage)
→ RunnableTarget
→ CoverageEquivalence
→ BucketGate
→ ExplanationReport
```

---

## Non-negotiable safety invariants

1. Public API source of truth is `interface_sdk-js/api`.
2. Internal C++ symbols, native bridge names, ANI/NDK names, generated accessor names are **evidence only** — never public API identity.
3. No direct `file → test` hardcode in production code or config.
4. No `case_id`-specific production logic.
5. No broad aliases (e.g. `bubble→common`, `jsi→all APIs`, `gesture→all components`).
6. `path-only`, `import-only`, `artifact-only`, `score-only` evidence cannot produce genuine `must_run`.
7. `must_run` requires **all** of:
   - strong source impact evidence
   - SDK-visible API declaration
   - strong XTS consumer usage evidence (non-import-only)
   - exact coverage equivalence
   - confirmed runnable target
8. Broad infra profiles emit only `recommended` or `possible`, never `must_run`.
9. Unknown/ambiguous impact → `unresolved`, `possible`, or `needs_review` with explicit reason.
10. `false_must_run` must remain **0** at all times.
11. Old accepted baseline of **212 manual_verified** cases must not change unless explicitly requested with full evidence.
12. PR-derived `generated_candidate` and `needs_review` are benchmark/candidate corpus, **not accepted truth**.
13. Graph resolver must remain **default-off** for broad changed-file runs.
14. Do not weaken golden quality gates.
15. Do not make `view_abstract`/`js_view_abstract` broad-file changes produce `must_run`.

---

## Corpus policy

### Current split

| Status | Count | Meaning |
|---|---|---|
| `manual_verified` | 212 | Accepted release truth. SDK evidence + 2 strong types confirmed. |
| `generated_candidate` | 64 | Selector-resolved snapshot. Not accepted truth. |
| `needs_review` | 92 | Known coverage gap. Expected APIs from signals only. |
| **total** | **368** | |

### Promotion rules

`generated_candidate` / `needs_review` → `manual_verified` only when:
- source path exists in `ARKUI_ACE_ENGINE_ROOT`
- SDK-visible API declared in `interface_sdk-js/api`
- ≥ 2 strong evidence types
- selector validation passes
- `false_must_run` remains 0

### PR-derived case rules

- Every PR-derived case must have a `notes` field with `"PR !NNN — description"` source marker.
- PR-derived cases must include explicit `allow_unresolved: true` or `needs_review` status.
- New PR-derived cases must never set `status: manual_verified` without full promotion criteria above.

---

## Universal impact architecture

Follow the layered resolver architecture from `docs/UNIVERSAL-IMPACT-RESOLUTION-DESIGN-2026-05-20.md`.

### Layer rules

**Source classifier** (`impact/source_classifier.py`):
- Classifies path/symbols into `SourceImpactEntity` with `layer`, `role`, `owner_family_hint`, `source_topic_hints`.
- Does not produce API claims or test targets.
- Config: `config/source_layers.json` (29 rules, do not add aliases here).

**Topic resolvers** (`impact/*_api_resolver.py`):
- Input: `SourceImpactEntity`.
- Output: `ImpactTopic` + `SdkApiTopic`.
- Never output internal C++ names as public SDK API identities.
- Missing SDK declaration → `sdk_declaration_missing` unresolved reason.
- Do not select XTS targets at this layer.

**XTS linker** (`impact/*_xts_linker.py`):
- Input: `SdkApiTopic`.
- Output: `ConsumerUsageEdge` from XTS usage index.
- Import-only → `confidence=weak`, cannot reach `must_run`.
- Use `XTS_ACTS_ROOT` env var; degrade gracefully when unset.

**Bucket gate**:
- `ImpactTopic` only → `possible`
- `ImpactTopic` + SDK declaration → `possible`
- `ImpactTopic` + SDK declaration + XTS usage → `recommended`
- Exact coverage equivalence + runnable target → `must_run` allowed
- Broad infra profiles → capped at `recommended`

**Fanout limiter**:
- Direct SDK API usage outranks broad profiles.
- Broad fanout cannot promote bucket level.
- `CommonMethod` → member-specific; never `common/common` all.

---

## Resolver implementation rules

- `GestureApiResolver`: gesture domain only (`components_ng/gestures/**`, `gesture_impl.cpp`). `max_bucket=possible` without XTS usage.
- `NativePeerResolver`: `interfaces/native/implementation/**`. Family from filename = lookup hint only.
- `AniBridgeResolver`: `interfaces/native/ani/**`. ANI names = bridge evidence, not public API.
- `NativeEventResolver`: `interfaces/native/event/**`. Separate NDK targets from ArkTS event fanout.
- `BroadInfraProfileResolver`: JSI/inspector/overlay. Runs after direct topic/usage. Never `must_run`.
- Any new resolver must have its own test file before merge.

---

## Phase discipline

One vertical slice per patch. Do not implement multiple resolver domains in one commit unless explicitly requested.

### Roadmap

| Phase | Scope | Status |
|---|---|---|
| A | Source classifier + PR benchmark harness | **Done** (commit `3d81fd1`) |
| B.1 | GestureApiResolver — ImpactTopics | **Done** (commit `9b02a0a`) |
| B.2 | Gesture SDK validation + XTS usage edges | **Done** (commit `f37890e`) |
| B.3 | NativePeerResolver + AniBridgeResolver | Pending |
| B.4 | NativeEventResolver | Pending |
| C | XTS consumer linker generalization | Pending |
| D | BroadInfraProfileResolver (JSI, inspector, overlay) | Pending |
| E | FanoutLimiter + PR benchmark acceptance | Pending |
| F | hunk/symbol precision expansion | Pending |
| G | Developer workflow / CI hardening | Pending |

---

## Required validation commands

### Before starting any implementation

```bash
git status --short --branch
python3 -m pytest --collect-only -q
make validate-fast
make validate-graph
python3 -m pytest tests/golden/test_golden_cases.py tests/test_golden_corpus_integrity.py -q
```

Record: `manual_verified` count, `false_must_run`, `expected_api_missing`.

### After changing selector/golden/API behavior

```bash
python3 tests/golden/tools/run_manual_golden_validation.py
```

Note: requires `ARKUI_ACE_ENGINE_ROOT`, `INTERFACE_SDK_JS_ROOT`, `XTS_ACTS_ROOT` set. If env unavailable, run targeted tests and state what was skipped.

### After changing universal impact layer

```bash
python3 -m pytest tests/test_source_classifier.py tests/test_pr_benchmark_source_classification.py -q
python3 -m pytest tests/test_golden_corpus_integrity.py -q
# plus phase-specific tests
```

### Targeted tests (focused changes)

```bash
python3 -m pytest tests/test_gate_adapter.py -q
python3 -m pytest tests/test_structured_api_details.py -q
python3 -m pytest tests/test_bucket_gate_policy.py -q
```

---

## Reporting requirements

Every phase report → `docs/<PHASE-NAME>-REPORT-YYYY-MM-DD.md`.

Required sections:
- files changed
- commands run with output
- before/after metrics: `manual_verified`, `generated_candidate`, `needs_review`, `false_must_run`, `expected_api_missing`
- benchmark impact (PR 84287, PR 83382 or relevant PRs)
- safety checks (no file→test hardcode, no broad must_run, SDK declarations required)
- unresolved limitations
- verdict: GREEN / YELLOW / RED

**GREEN**: all gates pass, `false_must_run=0`, accepted baseline unchanged.
**YELLOW**: gates pass but real-env validation not run, or XTS usage incomplete.
**RED**: any gate failure, `false_must_run > 0`, or accepted baseline changed unexpectedly.

---

## Commit rules

- Commit only relevant files.
- Do not commit: caches, local env files, large api_graph outputs, `/tmp` artifacts, nightly reports.
- Keep working tree clean before and after.
- Do not push unless explicitly requested.
- Commit message format: `feat/test/docs/fix/chore: <scope> (<phase if applicable>)`.

---

## Environment variables

| Var | Purpose |
|---|---|
| `ARKUI_ACE_ENGINE_ROOT` | `~/proj/ohos_master/foundation/arkui/ace_engine` |
| `INTERFACE_SDK_JS_ROOT` | `~/proj/ohos_master/interface/sdk-js` |
| `XTS_ACTS_ROOT` | `~/proj/ohos_master/test/xts/acts/arkui` |
| `ARKUI_XTS_CACHE_DIR` | `~/.cache/arkui_xts_selector` |

All resolvers must degrade gracefully when these are unset.

---

## Golden case evidence types (reference)

Valid strong evidence:
- `sdk_declaration` — from `interface_sdk-js/api`
- `source_class_or_method` — from `arkui_ace_engine` source
- `native_modifier_accessor` — native accessor/modifier link
- `bridge_symbol` — bridge/jsview binding
- `xts_usage` — XTS test file usage

Weak/insufficient alone:
- `path_layer` — filename / directory token only
- `signal_symbol` — from selector signal extraction, not SDK-confirmed
- `manual_note` — narrative without code evidence

`path_layer` and `signal_symbol` are never sufficient for `manual_verified`.
