# arkui-xts-selector

`arkui-xts-selector` is an impact-analysis CLI for OpenHarmony ArkUI workspaces.

It maps changed files to likely ArkUI XTS targets by correlating:
- changed native/ETS/TS/JS files in `foundation/arkui/ace_engine`
- ArkUI SDK symbols from `interface/sdk-js/api`
- actual XTS usage under `test/xts/acts`

This is not runtime coverage. It is a test selection helper.

## Features

- analyze changed files directly
- read changed files from Git diff or GitCode PR
- configurable XTS/SDK/git roots
- output `aa test`, `python -m xdevice`, and `runtest.sh` commands
- multi-device execution planning for `aa_test`, `xdevice`, and `runtest`
- opt-in `--run-now` execution with per-device status in JSON and human output
- explicit `unresolved_files` block for files with weak or unreliable matches
- product-build diagnostics via `out/<product>/build.log` and `error.log`
- code-search evidence for symbol queries, useful for reconstructing manual XTS lists
- timing metadata and opt-in debug traces for ranking analysis
- JSON report written to file by default, with stdout/file routing flags
- phase-progress messages enabled by default and written to stderr
- configurable changed-file exclusions for non-XTS paths such as `test/unittest` and `test/mock`

## Install For Development

```bash
cd arkui-xts-selector
python3 -m pip install -e .
```

## Basic Usage

```bash
arkui-xts-selector \
  --changed-file foundation/arkui/ace_engine/frameworks/core/interfaces/native/implementation/content_modifier_helper_accessor.cpp
```

```bash
arkui-xts-selector --symbol-query ButtonModifier
```

```bash
arkui-xts-selector --symbol-query ButtonModifier --json
```

```bash
arkui-xts-selector --symbol-query ButtonModifier --json-out reports/button.json
```

```bash
arkui-xts-selector --code-query ButtonModifier
```

```bash
arkui-xts-selector \
  --config config/selector.example.json \
  --pr-url https://gitcode.com/openharmony/arkui_ace_engine/pull/82225
```

```bash
arkui-xts-selector \
  --symbol-query ButtonModifier \
  --devices R52W12345678,192.168.0.10:8710 \
  --run-now \
  --run-tool auto
```

## Binary Packaging

Native packaging is supported for:
- Linux / Ubuntu -> `dist/arkui-xts-selector`
- Windows 11 -> `dist\arkui-xts-selector.exe`

Important limitation:
- build the Linux binary on Linux / Ubuntu
- build the Windows `.exe` on a native Windows build environment
- the current PyInstaller workflow does not try to cross-build a Windows `.exe` from Ubuntu

Linux / Ubuntu:

```bash
cd arkui-xts-selector
./scripts/build_linux.sh
./scripts/install_linux.sh dist/arkui-xts-selector /usr/local/bin
```

The Linux build script:
- ensures `pyinstaller` is available in the active Python environment
- runs a clean one-file build
- verifies that `dist/arkui-xts-selector` exists
- smoke-runs `dist/arkui-xts-selector --help`

Windows 11 PowerShell:

```powershell
cd arkui-xts-selector
./scripts/build_windows.ps1
./scripts/install_windows.ps1 -BinaryPath .\dist\arkui-xts-selector.exe -TargetDir C:\Tools
```

The Windows build script:
- ensures `pyinstaller` is available in the active Python environment
- runs a clean one-file build
- verifies that `dist\arkui-xts-selector.exe` exists
- smoke-runs `dist\arkui-xts-selector.exe --help`

## Config

Example config is in [config/selector.example.json](config/selector.example.json).

Recommended fields:
- `xts_root`
- `sdk_api_root`
- `git_repo_root`
- `acts_out_root`
- `path_rules_file`
- `composite_mappings_file`
- `changed_file_exclusions_file`
- `product_name`
- `system_size`
- `xts_suitetype`
- `git_host_config`
- `device`
- `devices`

## Rule Files

Special mapping rules are stored outside Python code where possible:

- [config/path_rules.json](config/path_rules.json)
  - path-token rules
  - module aliases
  - known ArkUI special cases

- [config/composite_mappings.json](config/composite_mappings.json)
  - helpers/accessors covering multiple components
  - shared/common-component mappings
  - cross-component bridge rules

- [config/changed_file_exclusions.json](config/changed_file_exclusions.json)
  - changed-file path prefixes that should be skipped for XTS analysis
  - default non-XTS roots such as `test/unittest` and `test/mock`

## Architecture

Project architecture is documented in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Built Artifacts

If built ACTS artifacts exist under `acts_out_root`, the tool reports their presence.

This is useful for future enrichment via:
- `testcases/*.json`
- `module_info.list`
- built hap/testcase metadata

If no built artifacts are present, the tool reports that explicitly.

It also inspects full product build state under `out/<product>` when `--product-name` is set:
- `build.log` presence
- `error.log` presence and size
- whether the last known build ended in a failure marker

It prints build guidance:
- full product build command
- full ACTS build command
- selected target ACTS build commands inferred from current results

## How A Manual List Can Be Obtained

A manual list such as the `ButtonModifier` set is usually reconstructed from source, not from runtime coverage:
- grep XTS sources for exact symbol usage such as `ButtonModifier`
- include related forms such as `implements AttributeModifier<ButtonAttribute>` and `extends ButtonModifier`
- map the matched files back to their owning `Test.json` projects
- optionally normalize dynamic/static variants and deduplicate by suite family

The CLI now prints `code_search_evidence` for `--symbol-query`, so you can see the raw source hits that likely produced such a manual list.

## Debug Workflow

Use `--json --debug-trace` when you need to inspect ranking behavior on stdout, or combine `--debug-trace` with the default file output.

The JSON report includes:
- `cache_used` to show whether the XTS index came from cache
- `timings_ms` for major analysis phases
- per-result `debug` counts for candidate vs matched projects
- `unresolved_debug` for why a changed file was downgraded to unresolved

Default human-readable output stays concise; the extra diagnostics are opt-in.

## Output Contract

Default behavior:
- progress messages are enabled and written to `stderr`
- machine-readable JSON is written to `./arkui_xts_selector_report.json`
- human-readable report is printed to `stdout`

JSON routing options:
- `--json` writes JSON to `stdout` instead of the default report file
- `--json-out <path>` writes JSON to a specific file path

Execution options:
- `--devices SERIAL1,SERIAL2,...` supplies multiple device serials/IPs
- `--devices-from <path>` loads device serials from a text file
- `--device <serial>` is still supported as the single-device shortcut
- `--run-now` executes the selected run targets after report generation
- `--run-tool auto|aa_test|xdevice|runtest` controls which launcher is used
- `--run-top-targets <N>` limits execution to the first N unique targets; `0` means all
- `--run-timeout <seconds>` sets a per-command timeout for `--run-now`

Progress options:
- progress is on by default
- `--no-progress` disables phase-progress messages

Changed-file exclusion options:
- built-in non-XTS roots such as `test/unittest` and `test/mock` are skipped before scoring
- excluded inputs are reported under `excluded_inputs` in JSON and human output
- `--changed-file-exclusions-file <path>` adds extra path prefixes to exclude from XTS analysis

Typical progress messages include:
- loading XTS project index
- loading SDK index
- building content modifier index
- scoring changed files / symbol queries / code queries
- planning target execution
- running selected targets
- writing JSON report
- rendering human report

## User Flow Scenarios

### Selector CLI

| Scenario | Typical command | Expected output |
| --- | --- | --- |
| Analyze one changed ArkUI file and get suggested XTS targets | `arkui-xts-selector --changed-file foundation/arkui/ace_engine/.../button_pattern.cpp` | Human report on stdout, JSON report on disk, `run_targets` with `aa_test`/`xdevice`/`runtest` commands |
| Reconstruct likely suites from a component or modifier name | `arkui-xts-selector --symbol-query ButtonModifier` | Ranked XTS projects, code-search evidence, and runnable targets for that symbol |
| Search codebase only, without test selection | `arkui-xts-selector --code-query ButtonModifier` | Matching code files in the report, no direct runtime execution required |
| Analyze a batch of changed files from a text list | `arkui-xts-selector --changed-files-from changed.txt` | Combined report for all listed files, unresolved items called out explicitly |
| Analyze changes from git diff or PR | `arkui-xts-selector --git-diff HEAD~1..HEAD` or `--pr-url <url>` | Changed-file set resolved automatically, then normal ranking/build-guidance flow |
| Run from a shared workspace config | `arkui-xts-selector --config config/selector.example.json --symbol-query ButtonModifier` | Same selection flow, but roots/product/device defaults come from config |
| Plan execution only for one or more devices | `arkui-xts-selector --symbol-query ButtonModifier --devices SER1,SER2` | Report includes per-device execution plan, but does not start tests |
| Execute selected targets immediately through `hdc`/`xdevice`/`runtest` | `arkui-xts-selector --symbol-query ButtonModifier --devices SER1,SER2 --run-now --run-tool auto` | Per-device execution results in JSON/human output, non-zero exit if execution was requested and failures occurred |
| Limit blast radius of execution | `arkui-xts-selector --changed-file ... --run-now --run-top-targets 3 --run-timeout 600` | Only the first N unique targets are executed, with timeout-aware status reporting |

### `xts_compare`

| Scenario | Typical command | Expected output |
| --- | --- | --- |
| Inspect one XTS run quickly | `python3 -m arkui_xts_selector.xts_compare /path/to/run.zip` | Single-run summary in terminal |
| Export one XTS run as standalone HTML | `python3 -m arkui_xts_selector.xts_compare /path/to/run.zip --html -o single-run.html` | Shareable HTML summary for one run |
| Compare base vs target run | `python3 -m arkui_xts_selector.xts_compare base.zip target.zip` | Compare report with regressions, improvements, health, performance, and provenance |
| Compare with explicit labels and machine-readable output | `python3 -m arkui_xts_selector.xts_compare --base base.zip --target target.zip --labels "base,fix" -o report.json` | JSON compare report with `input_order`, `timestamp_source`, `archive_diagnostics`, and transitions |
| Build a timeline across several runs | `python3 -m arkui_xts_selector.xts_compare --timeline run1.zip run2.zip run3.zip` | Timeline report showing trends across runs |
| Auto-discover archives from a results directory | `python3 -m arkui_xts_selector.xts_compare /path/to/results-dir/` | `1` archive -> single-run, `2` archives -> compare, `3+` archives -> timeline |
| Scan nested archive trees with filters | `python3 -m arkui_xts_selector.xts_compare /path/to/results-dir/ --scan-recursive --scan-glob "device-a/*.zip" --scan-limit 5` | Ordered subset of archives selected automatically before single-run/compare/timeline dispatch |
| Triage only regressions for CI | `python3 -m arkui_xts_selector.xts_compare base.zip target.zip --regressions-only` | Summary plus the regression section only, exit `1` if regressions exist |
| Inspect blocked noise or archive safety issues | `python3 -m arkui_xts_selector.xts_compare base.zip target.zip --show-stable-blocked` or `--strict-archive` | Either deeper blocked-case visibility or hard failure on skipped special archive entries |
| Correlate compare output with selector predictions | `python3 -m arkui_xts_selector.xts_compare base.zip target.zip --selector-report arkui_xts_selector_report.json` | Added `Selector Correlation` block for predicted vs actual coverage |

## XTS Compare

`xts_compare` compares two XTS result runs or builds a timeline across several runs.

Basic usage:

```bash
python3 -m arkui_xts_selector.xts_compare \
  /path/to/base.zip /path/to/target.zip
```

```bash
python3 -m arkui_xts_selector.xts_compare \
  --base /path/to/base.zip \
  --target /path/to/target.zip
```

```bash
python3 -m arkui_xts_selector.xts_compare \
  /path/to/results-dir/
```

```bash
python3 -m arkui_xts_selector.xts_compare \
  /path/to/run-or-archive.zip --html -o single-run.html
```

```bash
python3 -m arkui_xts_selector.xts_compare \
  --timeline run1.zip run2.zip run3.zip \
  --labels "base,fix1,fix2"
```

```bash
python3 -m arkui_xts_selector.xts_compare \
  run1.zip run2.zip -o report.json
```

```bash
python3 -m arkui_xts_selector.xts_compare \
  run1.zip run2.zip -o report.html
```

```bash
python3 -m arkui_xts_selector.xts_compare \
  --base run1.zip --target run2.zip \
  --suite-filter "ButtonStyle*" \
  --failure-type crash,timeout \
  --sort severity \
  --min-time-delta 250 \
  --min-time-ratio 2.0
```

```bash
python3 -m arkui_xts_selector.xts_compare \
  --base run1.zip --target run2.zip \
  --regressions-only
```

```bash
python3 -m arkui_xts_selector.xts_compare \
  --base run1.zip --target run2.zip \
  --show-stable-blocked
```

```bash
python3 -m arkui_xts_selector.xts_compare \
  /path/to/results-dir/
  # 1 archive -> single-run summary
  # 2 archives -> compare
  # 3+ archives -> timeline
```

```bash
python3 -m arkui_xts_selector.xts_compare \
  /path/to/results-dir/ \
  --scan-recursive \
  --scan-glob "device-a/*.zip" \
  --scan-limit 5
```

```bash
python3 -m arkui_xts_selector.xts_compare \
  --base run1.zip --target run2.zip \
  --selector-report arkui_xts_selector_report.json
```

Optional report inputs parsed by `load_run()` when present:
- `summary_report.xml` for test-level outcomes
- `summary.ini` for run metadata
- `task_info.record` for structured unsuccessful test entries
- `static/data.js` for module-level error/timing metadata and log references
- crash logs referenced from `data.js` such as `cppcrash-*.log`

Accepted run inputs:
- plain result directories
- `.zip` archives
- `.tar.gz` archives

JSON reports include additive run metadata under:
- `task_info`
- `module_infos`
- `timestamp_source`
- `archive_diagnostics`
- `input_order` for compare/timeline mode

Terminal compare reports now support:
- positional compare mode: `xts_compare base.zip target.zip`
- direct single-run mode from one archive or one extracted result directory
- directory-scan mode from one directory argument
- `--scan-recursive`, `--scan-glob`, and `--scan-limit`
- `--suite-filter` and `--case-filter`
- `--failure-type` with comma-separated values such as `crash,timeout`
- `--sort module|severity|time-delta`
- `--min-time-delta` and `--min-time-ratio` for performance-change detection
- `--html` for a standalone shareable report with embedded CSS and JS
- `--strict-archive` to reject archives containing skipped special entries
- `--regressions-only` for CI-focused terminal output
- `--show-stable-blocked` to inspect tests blocked in both runs
- `--selector-report` to correlate selector predictions with actual regressions

When thresholds are met, the report also renders:
- `Module Health`
- `Performance Changes`
- advisory tips such as dominant failure-type hints

When `--selector-report` is provided, the report also renders:
- `Selector Correlation`

If the optional files are absent or malformed, `xts_compare` falls back to the XML-based comparison pipeline.

Auto behaviors:
- positional compare mode auto-orders the two runs by `summary.ini:start_time`, then by timestamp in filename, then alphabetically
- positional timeline mode auto-orders runs by the same provenance chain
- `-o/--output report.json` infers JSON mode when no explicit output mode is set
- `-o/--output report.html` infers HTML mode when no explicit output mode is set
- `--html` without `-o/--output` auto-generates `xts_compare_YYYYMMDD_HHMMSS.html`
- single-run HTML also auto-generates `xts_run_YYYYMMDD_HHMMSS.html` when `--html` is used without `-o/--output`
- when regressions are present and `--sort` is omitted, compare output defaults to `severity`
- when regressions are zero but persistent failures exist, compare output auto-enables the persistent-fail section
