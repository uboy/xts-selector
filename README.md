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
- auto-discover a full OHOS workspace from the current tree or a sibling checkout such as `ohos_master`
- configurable XTS/SDK/git roots
- optional daily-prebuilt ACTS reuse from official OpenHarmony full packages, so `xdevice` can run without a local XTS build
- standalone daily artifact download for XTS, SDK, and dayu200 firmware packages
- optional dayu200 firmware flashing through the same CLI using `hdc` + Rockchip `flash.py`
- output `aa test`, `python -m xdevice`, and `runtest.sh` commands
- multi-device execution planning for `aa_test`, `xdevice`, and `runtest`
- device preflight before `--run-now`, including `hdc list targets` checks for connected devices
- opt-in `--run-now` execution with per-device status in JSON and human output
- optional labeled run storage under `.runs/<label>/<timestamp>/` for later audit and comparison
- shard execution mode that can split selected unique targets across multiple devices
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

If you prefer to run directly from the repository checkout without installing the package, use:

```bash
PYTHONPATH=src python3 -m arkui_xts_selector --help
PYTHONPATH=src python3 -m arkui_xts_selector.xts_compare --help
```

## Quick Start

1. Inspect the available commands:

```bash
arkui-xts-selector --help
python3 -m arkui_xts_selector.xts_compare --help
```

2. Run one selector query:

```bash
arkui-xts-selector --changed-file foundation/arkui/ace_engine/frameworks/core/interfaces/native/implementation/content_modifier_helper_accessor.cpp
```

3. Plan or execute targets on a device:

```bash
arkui-xts-selector \
  --symbol-query ButtonModifier \
  --devices R52W12345678 \
  --run-tool xdevice \
  --run-now
```

4. Compare two labeled runs later:

```bash
python3 -m arkui_xts_selector.xts_compare \
  --base-label baseline \
  --target-label candidate
```

Use [docs/CLI_REFERENCE.md](docs/CLI_REFERENCE.md) for the full command reference, grouped flags, and extra examples.

## Documentation

- [docs/CLI_REFERENCE.md](docs/CLI_REFERENCE.md) - detailed CLI reference for `arkui-xts-selector` and `xts_compare`
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) - project structure, indexes, and execution flow
- [docs/REQUIREMENTS.md](docs/REQUIREMENTS.md) - scope and expected behavior
- [docs/DESIGN.md](docs/DESIGN.md) - design notes and implementation direction

## Common Examples

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
  --pr-url https://gitcode.com/openharmony/arkui_ace_engine/pull/82225 \
  --pr-source api \
  --git-host-config ../gitee_util/config.ini
```

```bash
arkui-xts-selector \
  --symbol-query ButtonModifier \
  --devices R52W12345678,192.168.0.10:8710 \
  --run-label baseline \
  --run-now \
  --run-tool xdevice \
  --shard-mode split
```

```bash
arkui-xts-selector \
  --symbol-query ButtonModifier \
  --daily-build-tag 20260403_120242 \
  --daily-component dayu200_Dyn_Sta_XTS \
  --run-tool xdevice
```

```bash
arkui-xts-selector \
  --download-daily-tests \
  --daily-build-tag 20260404_120510 \
  --json
```

```bash
arkui-xts-selector \
  --download-daily-sdk \
  --sdk-build-tag 20260404_120537 \
  --sdk-component ohos-sdk-public \
  --json
```

```bash
arkui-xts-selector \
  --flash-daily-firmware \
  --firmware-build-tag 20260404_120244 \
  --firmware-component dayu200 \
  --device 150100424a544434520369864f628800 \
  --flash-py-path /home/<user>/bin/linux/flash.py
```

```bash
python3 -m arkui_xts_selector.xts_compare \
  --base-label baseline \
  --target-label v1
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
- `repo_root`
- `xts_root`
- `sdk_api_root`
- `git_repo_root`
- `acts_out_root`
- `run_store_root`
- `daily_build_tag`
- `daily_component`
- `daily_branch`
- `daily_date`
- `daily_cache_root`
- `sdk_build_tag`
- `sdk_component`
- `sdk_branch`
- `sdk_date`
- `sdk_cache_root`
- `firmware_build_tag`
- `firmware_component`
- `firmware_branch`
- `firmware_date`
- `firmware_cache_root`
- `flash_py_path`
- `hdc_path`
- `path_rules_file`
- `composite_mappings_file`
- `ranking_rules_file`
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

- [config/ranking_rules.json](config/ranking_rules.json)
  - family-group normalization for coverage planning
  - generic and umbrella markers used by ranking
  - scope/bucket/quality/planner coefficients

- [config/README.md](config/README.md)
  - explains what each config file controls
  - describes how to add or remove ranking rules safely

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
- `--daily-build-tag <tag>` resolves an official daily build and prepares prebuilt ACTS artifacts from its full package
- `--daily-component <name>` selects the daily build component, for example `dayu200_Dyn_Sta_XTS`
- `--daily-branch <name>` filters the daily build search by branch, default `master`
- `--daily-date <YYYYMMDD>` constrains the daily build lookup when the date cannot be inferred from the tag
- `--daily-cache-root <path>` controls where downloaded and extracted full packages are cached
- `--download-daily-tests` downloads/extracts the XTS daily package described by `--daily-*` and exits
- `--download-daily-sdk` downloads/extracts the SDK daily package described by `--sdk-*` and exits
- `--download-daily-firmware` downloads/extracts the firmware image package described by `--firmware-*` and exits
- `--flash-daily-firmware` downloads/extracts the firmware image package described by `--firmware-*`, flashes the board, and exits
- `--sdk-build-tag <tag>` selects the SDK daily build tag
- `--sdk-component <name>` selects the SDK daily component, default `ohos-sdk-public`
- `--sdk-branch <name>` filters the SDK daily build search by branch, default `master`
- `--sdk-date <YYYYMMDD>` constrains the SDK daily lookup when the date cannot be inferred from the tag
- `--sdk-cache-root <path>` controls where downloaded/extracted SDK packages are cached
- `--firmware-build-tag <tag>` selects the firmware daily build tag
- `--firmware-component <name>` selects the firmware daily component, default `dayu200`
- `--firmware-branch <name>` filters the firmware daily build search by branch, default `master`
- `--firmware-date <YYYYMMDD>` constrains the firmware daily lookup when the date cannot be inferred from the tag
- `--firmware-cache-root <path>` controls where downloaded/extracted firmware packages are cached
- `--flash-py-path <path>` points to the Rockchip `flash.py` helper used for board flashing
- `--hdc-path <path>` overrides the `hdc` binary used for bootloader switching before flashing
- `--run-now` executes the selected run targets after report generation
- `--run-label <label>` stores the planned or executed selector run under `.runs/<label>/<timestamp>/`
- `--run-store-root <path>` overrides the default labeled-run storage location
- `--run-tool auto|aa_test|xdevice|runtest` controls which launcher is used
- `--shard-mode mirror|split` controls whether every device runs the same targets or the targets are sharded across devices
- `--run-top-targets <N>` limits execution to the first N unique targets; `0` means all
- `--run-timeout <seconds>` sets a per-command timeout for `--run-now`

Run-label notes:
- labeled runs are stored in the selector repo by default, not inside the OHOS workspace
- compare-by-label is intended for xdevice-backed runs, because they produce result directories that `xts_compare` can load
- `aa test` and `runtest` labeled runs are still stored for audit, but they are not guaranteed to be comparable later

Daily-prebuilt notes:
- the selector still analyzes source trees from `ohos_master`; prebuilt daily packages are only used as a source of ready ACTS artifacts for execution
- the tool uses the full daily package (`obsPath`), not the image-only `*_img.tar.gz`
- after extraction it heuristically discovers the best ACTS root by locating `testcases/module_info.list` and companion testcase JSON files

Utility-mode notes:
- utility-mode operations run before selector analysis and do not require `--changed-file`, `--symbol-query`, or `--code-query`
- daily defaults currently track the real DCP `openharmony/master` components observed on 2026-04-04:
  - tests: `dayu200_Dyn_Sta_XTS`
  - SDK: `ohos-sdk-public`
  - firmware: `dayu200`
- firmware flashing currently targets the local Rockchip Linux flow that worked for dayu200:
  - switch the board into bootloader through `hdc target boot -bootloader`
  - wait for Rockchip `Loader`
  - run `flash.py -a -i <image_bundle>`

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

In practice, a user can use the tool to:
- choose likely XTS suites by changed ArkUI files
- choose likely XTS suites by component, modifier, or attribute name such as `ButtonModifier`
- search the indexed codebase without launching tests
- analyze a git diff, a PR, or a text file with changed paths
- run with a shared JSON config instead of repeating workspace paths on every command
- prepare daily prebuilt test artifacts and point execution at them
- plan device-targeted execution without launching it yet
- run selected targets immediately through `aa test`, `xdevice`, or `runtest`
- distribute selected targets across several devices with `--shard-mode split`
- store labeled runs under `.runs/` and compare them later with `xts_compare`
- download daily SDK or firmware artifacts as standalone utility actions
- flash a supported device image bundle through the same CLI
- export JSON, HTML, or Markdown artifacts for automation and reporting

Current limitation:
- multi-device distribution is supported, but the README intentionally does not describe it as true parallel execution. `--shard-mode split` assigns work across devices; it is not the new parallel scheduler design that is still being discussed separately.

### Selector CLI

| Scenario | Typical command | Expected output |
| --- | --- | --- |
| Analyze one changed ArkUI file and get suggested XTS targets | `arkui-xts-selector --changed-file foundation/arkui/ace_engine/.../button_pattern.cpp` | Human report on stdout, JSON report on disk, `run_targets` with `aa_test`/`xdevice`/`runtest` commands |
| Reconstruct likely suites from a component or modifier name | `arkui-xts-selector --symbol-query ButtonModifier` | Ranked XTS projects, code-search evidence, and runnable targets for that symbol |
| Reconstruct likely suites from an attribute or API name | `arkui-xts-selector --symbol-query ButtonAttribute` | Ranked XTS projects for the requested API surface, including evidence and runnable targets |
| Search codebase only, without test selection | `arkui-xts-selector --code-query ButtonModifier` | Matching code files in the report, no direct runtime execution required |
| Analyze a batch of changed files from a text list | `arkui-xts-selector --changed-files-from changed.txt` | Combined report for all listed files, unresolved items called out explicitly |
| Analyze changes from git diff or PR | `arkui-xts-selector --git-diff HEAD~1..HEAD` or `--pr-url <url>` | Changed-file set resolved automatically, then normal ranking/build-guidance flow |
| Force PR resolution through GitCode API | `arkui-xts-selector --pr-url <url> --pr-source api --git-host-config ../gitee_util/config.ini` | PR file list comes from GitCode API instead of git fetch, useful when local refs are stale or the PR is already merged |
| Run from a shared workspace config | `arkui-xts-selector --config config/selector.example.json --symbol-query ButtonModifier` | Same selection flow, but roots/product/device defaults come from config |
| Reuse official daily prebuilt ACTS artifacts | `arkui-xts-selector --symbol-query ButtonModifier --daily-build-tag 20260403_120242 --daily-component dayu200_Dyn_Sta_XTS --run-tool xdevice` | Selector keeps using local source trees for analysis, but execution commands point at ACTS suites extracted from the downloaded full package |
| Download a daily test package without running selector analysis | `arkui-xts-selector --download-daily-tests --daily-build-tag 20260404_120510` | Utility-mode download/extract flow only, then exit |
| Download a daily SDK package for local workspace reuse | `arkui-xts-selector --download-daily-sdk --sdk-build-tag 20260404_120537` | Utility-mode SDK download/extract flow only, then exit |
| Download a daily firmware package without flashing | `arkui-xts-selector --download-daily-firmware --firmware-build-tag 20260404_120244` | Utility-mode firmware download/extract flow only, then exit |
| Flash a board from the daily firmware bundle | `arkui-xts-selector --flash-daily-firmware --firmware-build-tag 20260404_120244 --firmware-component dayu200 --device <serial> --flash-py-path /path/to/flash.py` | Download, extract, switch to bootloader, and run the local Rockchip flashing flow |
| Plan execution only for one or more devices | `arkui-xts-selector --symbol-query ButtonModifier --devices SER1,SER2` | Report includes per-device execution plan, but does not start tests |
| Execute selected targets immediately through `hdc`/`xdevice`/`runtest` | `arkui-xts-selector --symbol-query ButtonModifier --devices SER1,SER2 --run-now --run-tool auto` | Per-device execution results in JSON/human output, with device/tool preflight before launch |
| Limit blast radius of execution | `arkui-xts-selector --changed-file ... --run-now --run-top-targets 3 --run-timeout 600` | Only the first N unique targets are executed, with timeout-aware status reporting |
| Keep a labeled baseline or versioned run | `arkui-xts-selector --symbol-query ButtonModifier --run-now --run-tool xdevice --run-label baseline` | Selector report plus run manifest are persisted under `.runs`, ready for later compare-by-label |
| Distribute selected targets across multiple devices | `arkui-xts-selector --changed-file ... --devices SER1,SER2,SER3 --run-now --shard-mode split` | The execution plan assigns each unique target to one device instead of mirroring everything to all devices; this is device distribution, not a separate documented parallel scheduler mode |
| Emit machine-readable output for automation | `arkui-xts-selector --symbol-query ButtonModifier --json-out reports/button.json` | Human output still goes to stdout, while JSON is written to a specific file |
| Inspect ranking details when selection looks suspicious | `arkui-xts-selector --symbol-query ButtonModifier --json --debug-trace` | JSON includes timings, cache usage, and extra ranking diagnostics |

### `xts_compare`

| Scenario | Typical command | Expected output |
| --- | --- | --- |
| Inspect one XTS run quickly | `python3 -m arkui_xts_selector.xts_compare /path/to/run.zip` | Single-run summary in terminal |
| Export one XTS run as standalone HTML | `python3 -m arkui_xts_selector.xts_compare /path/to/run.zip --html -o single-run.html` | Shareable HTML summary for one run |
| Compare base vs target run | `python3 -m arkui_xts_selector.xts_compare base.zip target.zip` | Compare report with regressions, improvements, health, performance, and provenance |
| Export compare or single-run output as Markdown | `python3 -m arkui_xts_selector.xts_compare base.zip target.zip --markdown -o report.md` | Shareable Markdown artifact generated from the native compare models |
| Compare two stored labeled runs | `python3 -m arkui_xts_selector.xts_compare --base-label baseline --target-label v1` | Resolves the latest comparable selector runs for each label, then renders the normal compare report |
| Compare with explicit labels and machine-readable output | `python3 -m arkui_xts_selector.xts_compare --base base.zip --target target.zip --labels "base,fix" -o report.json` | JSON compare report with `input_order`, `timestamp_source`, `archive_diagnostics`, and transitions |
| Build a timeline across several runs | `python3 -m arkui_xts_selector.xts_compare --timeline run1.zip run2.zip run3.zip` | Timeline report showing trends across runs |
| Auto-discover archives from a results directory | `python3 -m arkui_xts_selector.xts_compare /path/to/results-dir/` | `1` archive -> single-run, `2` archives -> compare, `3+` archives -> timeline |
| Scan nested archive trees with filters | `python3 -m arkui_xts_selector.xts_compare /path/to/results-dir/ --scan-recursive --scan-glob "device-a/*.zip" --scan-limit 5` | Ordered subset of archives selected automatically before single-run/compare/timeline dispatch |
| Triage only regressions for CI | `python3 -m arkui_xts_selector.xts_compare base.zip target.zip --regressions-only` | Summary plus the regression section only, exit `1` if regressions exist |
| Inspect blocked noise or archive safety issues | `python3 -m arkui_xts_selector.xts_compare base.zip target.zip --show-stable-blocked` or `--strict-archive` | Either deeper blocked-case visibility or hard failure on skipped special archive entries |
| Correlate compare output with selector predictions | `python3 -m arkui_xts_selector.xts_compare base.zip target.zip --selector-report arkui_xts_selector_report.json` | Added `Selector Correlation` block for predicted vs actual coverage |

## Purpose And Boundaries

`arkui-xts-selector` is still a selector-first tool.

It is meant to:
- map ArkUI changes to likely XTS targets;
- help launch the selected targets;
- preserve enough execution metadata to audit and compare those runs later.

It is not meant to replace a full CI scheduler or device-lab orchestrator. The execution and compare features are there to close the loop around targeted validation, not to become a generic test farm.

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

```bash
python3 -m arkui_xts_selector.xts_compare \
  --base run1.zip --target run2.zip \
  --markdown -o report.md
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
- `--markdown` for a shareable Markdown report in compare or single-run mode
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
