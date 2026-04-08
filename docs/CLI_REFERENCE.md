# CLI Reference

This document describes the current command-line interface for:

- `arkui-xts-selector` - select likely ArkUI XTS targets for changed files, symbols, or code queries
- `python3 -m arkui_xts_selector.xts_compare` - inspect, compare, and timeline XTS result archives or extracted runs

## Running The Tools

Installed entrypoint:

```bash
arkui-xts-selector --help
```

Run directly from the repository checkout:

```bash
PYTHONPATH=src python3 -m arkui_xts_selector --help
PYTHONPATH=src python3 -m arkui_xts_selector.xts_compare --help
```

## `arkui-xts-selector`

### What It Does

`arkui-xts-selector` is an impact-analysis CLI. It maps ArkUI source changes to likely XTS targets by correlating:

- changed files from `foundation/arkui/ace_engine`
- SDK symbols from `interface/sdk-js/api`
- actual XTS usage under `test/xts/acts`

It can also:

- prepare runnable `aa test`, `xdevice`, and `runtest` commands
- execute selected targets with `--run-now`
- download daily test, SDK, and firmware artifacts
- flash supported firmware packages
- store labeled runs under `.runs/<label>/<timestamp>/`

### Normal Mode Vs Utility Mode

Normal selector mode requires at least one query source:

- `--changed-file`
- `--changed-files-from`
- `--git-diff`
- `--pr-url`
- `--pr-number`
- `--symbol-query`
- `--code-query`

Utility mode runs before selector analysis and exits after completing the requested operation:

- `--download-daily-tests`
- `--download-daily-sdk`
- `--download-daily-firmware`
- `--flash-daily-firmware`

### Typical Flow

1. Choose one or more query sources.
2. Optionally point the CLI at a specific workspace or config file.
3. Optionally add device and execution flags.
4. Optionally add daily-package flags if you want prebuilt ACTS, SDK, or firmware artifacts.
5. Choose JSON routing if you want machine-readable output somewhere other than the default report file.

### Command Forms

Analyze one changed file:

```bash
arkui-xts-selector --changed-file path/to/file.cpp
```

Analyze by symbol name:

```bash
arkui-xts-selector --symbol-query ButtonModifier
```

Analyze by Git diff:

```bash
arkui-xts-selector --git-diff HEAD~1..HEAD
```

Analyze a GitCode PR:

```bash
arkui-xts-selector --pr-url https://gitcode.com/openharmony/arkui_ace_engine/pull/82225
```

Plan a device run:

```bash
arkui-xts-selector --symbol-query ButtonModifier --devices SER1,SER2
```

Execute selected targets now:

```bash
arkui-xts-selector \
  --symbol-query ButtonModifier \
  --devices SER1,SER2 \
  --run-now \
  --run-tool xdevice
```

### Option Reference

#### Query Inputs

- `--changed-file PATH`
  Add one changed file path. The flag can be repeated.
- `--changed-files-from PATH`
  Load changed files from a text file, one path per line.
- `--symbol-query NAME`
  Find likely XTS suites for a component or symbol such as `ButtonModifier`.
- `--code-query NAME`
  Search the indexed codebase for matching code files without focusing on XTS selection.

#### Git And PR Inputs

- `--git-diff REF`
  Resolve changed files from a local git diff range such as `HEAD~1..HEAD`.
- `--git-root PATH`
  Override the git root used with `--git-diff`.
- `--pr-url URL`
  Resolve changed files from a GitCode PR URL.
- `--pr-number NUMBER`
  Resolve changed files from a GitCode PR number.
- `--git-remote NAME`
  Override the git remote used for PR fetching.
- `--git-base-branch NAME`
  Override the PR base branch. Default: `master`.
- `--gitcode-api-url URL`
  GitCode API base URL for token-based PR fetching.
- `--gitcode-token TOKEN`
  GitCode access token for API mode.
- `--git-host-config PATH`
  Path to `gitee_util/config.ini` with `[gitcode]` credentials.

#### Workspace And Config

- `--config PATH`
  Load defaults from a JSON config file.
- `--repo-root PATH`
  Explicit OHOS workspace root. If omitted, the tool auto-discovers the workspace.
- `--xts-root PATH`
  Override the XTS root.
- `--sdk-api-root PATH`
  Override the SDK API root.
- `--acts-out-root PATH`
  Override the built ACTS output root used for `xdevice` command generation.
- `--path-rules-file PATH`
  Override the JSON file with path and alias mapping rules.
- `--composite-mappings-file PATH`
  Override the JSON file with multi-component mapping rules.
- `--ranking-rules-file PATH`
  Override the JSON file with family-group, generic-token, umbrella, and planner ranking rules.
- `--changed-file-exclusions-file PATH`
  Override the JSON file with extra changed-file exclusion prefixes.
- `--product-name NAME`
  Product name used for build guidance, for example `rk3568` or `m40`.
- `--system-size NAME`
  System-size hint for build guidance. Default: `standard`.
- `--xts-suitetype NAME`
  Optional `xts_suitetype` used for build guidance.

CLI flags take precedence over values loaded from `--config`.

#### Device Targeting And Execution

- `--device SERIAL`
  Single-device shortcut used mainly for generated `aa test` commands.
- `--devices SERIAL1,SERIAL2`
  Comma-separated device serials or `IP:PORT` endpoints for plan generation and execution.
  The flag can be repeated.
- `--devices-from PATH`
  Load device serials from a text file. Blank lines and `#` comments are ignored.
- `--run-now`
  Execute selected targets immediately after report generation.
- `--run-tool auto|aa_test|xdevice|runtest`
  Select the runtime launcher. Default: `auto`.
- `--shard-mode mirror|split`
  `mirror` runs the same selected targets on every device.
  `split` shards unique selected targets across devices.
- `--run-top-targets N`
  Execute at most `N` unique run targets. `0` means no limit.
- `--run-timeout SECONDS`
  Per-command timeout for `--run-now`. `0` disables the timeout.
- `--run-label LABEL`
  Persist the planned or executed run under `.runs/<label>/<timestamp>/`.
- `--run-store-root PATH`
  Override the labeled run-store root. Default: `<selector_repo>/.runs`.

#### Daily Prebuilt Tests, SDK, And Firmware

- `--daily-build-tag TAG`
  Daily build tag for test artifacts, for example `20260403_120242`.
- `--daily-component NAME`
  Daily test component, for example `dayu200_Dyn_Sta_XTS`.
  Plain board aliases such as `dayu200` are also accepted.
- `--daily-branch NAME`
  Branch filter for the daily test build lookup. Default: `master`.
- `--daily-date YYYYMMDD`
  Date filter for the daily test build lookup.
- `--daily-cache-root PATH`
  Cache directory for downloaded and extracted daily full packages.
- `--download-daily-tests`
  Download and extract the daily test package described by the `--daily-*` options, then exit.

- `--sdk-build-tag TAG`
  Daily SDK build tag.
- `--sdk-component NAME`
  Daily SDK component. Default: `ohos-sdk-public`.
- `--sdk-branch NAME`
  Branch filter for the SDK daily lookup. Default: `master`.
- `--sdk-date YYYYMMDD`
  Date filter for the SDK daily lookup.
- `--sdk-cache-root PATH`
  Cache directory for downloaded and extracted SDK packages.
- `--download-daily-sdk`
  Download and extract the daily SDK package, then exit.

- `--firmware-build-tag TAG`
  Daily firmware build tag.
- `--firmware-component NAME`
  Daily firmware component. Default: `dayu200`.
- `--firmware-branch NAME`
  Branch filter for the firmware daily lookup. Default: `master`.
- `--firmware-date YYYYMMDD`
  Date filter for the firmware daily lookup.
- `--firmware-cache-root PATH`
  Cache directory for downloaded and extracted firmware packages.
- `--download-daily-firmware`
  Download and extract the daily firmware package, then exit.
  When invoked through `ohos download firmware` without a tag, the wrapper lists recent available firmware tags and shows the next command to run.
- `--flash-daily-firmware`
  Download and extract the daily firmware package, flash the connected device, then exit.
  If the requested firmware tag does not exist, the CLI reports the error in the terminal and suggests recent valid firmware tags.
- `--flash-py-path PATH`
  Path to the Rockchip `flash.py` helper.
- `--hdc-path PATH`
  Path to `hdc`, used for switching the device into bootloader mode before flashing.

#### Filtering, Ranking, Cache, And Debug

- `--variants auto|static|dynamic|both`
  Filter returned candidates by variant. Default: `auto`.
- `--top-projects N`
  Advanced output control. Keep at most `N` ranked project results per query. Default: `12`.
- `--top-files N`
  Advanced output control. Keep at most `N` file-evidence entries per project. Default: `5`.
- `--keep-per-signature N`
  Deduplicate projects by coverage signature. `0` disables deduplication. `2` is the recommended guardrail value.
- `--cache-file PATH`
  Advanced override for the cached XTS project index path.
- `--no-cache`
  Disable cache reads and writes for the XTS project index.
- `--debug-trace`
  Add timing metadata and extra ranking diagnostics to the JSON report.
- `--progress`
  Explicitly enable phase-progress messages. This is already the default behavior.
- `--no-progress`
  Disable phase-progress messages.

#### Output Routing

- `--json`
  Write JSON to stdout instead of the default report file.
- `--json-out PATH`
  Write JSON to a specific file path.

Default output behavior:

- human-readable report -> stdout
- progress messages -> stderr
- machine-readable JSON -> `./arkui_xts_selector_report.json`

### Common Examples

Analyze one changed file:

```bash
arkui-xts-selector \
  --changed-file foundation/arkui/ace_engine/frameworks/core/interfaces/native/implementation/content_modifier_helper_accessor.cpp
```

Reconstruct likely suites for a symbol:

```bash
arkui-xts-selector --symbol-query ButtonModifier
```

Use a shared config file:

```bash
arkui-xts-selector \
  --config config/selector.example.json \
  --symbol-query ButtonModifier
```

Use a daily prebuilt package for later `xdevice` execution:

```bash
arkui-xts-selector \
  --symbol-query ButtonModifier \
  --daily-build-tag 20260403_120242 \
  --daily-component dayu200_Dyn_Sta_XTS \
  --run-tool xdevice
```

Download daily test artifacts only:

```bash
arkui-xts-selector \
  --download-daily-tests \
  --daily-build-tag 20260404_120510
```

Flash a firmware image bundle:

```bash
arkui-xts-selector \
  --flash-daily-firmware \
  --firmware-build-tag 20260404_120244 \
  --firmware-component dayu200 \
  --device 150100424a544434520369864f628800 \
  --flash-py-path /home/<user>/bin/linux/flash.py
```

List recent firmware tags through the `ohos` wrapper:

```bash
ohos download firmware
```

Download a firmware package with a positional tag:

```bash
ohos download firmware 20260408_120247
```

## `xts_compare`

### What It Does

`xts_compare` inspects one XTS run, compares two runs, or builds a timeline across several runs.
It accepts ZIP archives or extracted result directories produced by `xdevice`.

### Command Forms

Single-run summary:

```bash
python3 -m arkui_xts_selector.xts_compare /path/to/run.zip
```

Base vs target compare:

```bash
python3 -m arkui_xts_selector.xts_compare /path/to/base.zip /path/to/target.zip
```

Explicit compare form:

```bash
python3 -m arkui_xts_selector.xts_compare \
  --base /path/to/base.zip \
  --target /path/to/target.zip
```

Timeline mode:

```bash
python3 -m arkui_xts_selector.xts_compare \
  --timeline run1.zip run2.zip run3.zip
```

Compare by selector labels:

```bash
python3 -m arkui_xts_selector.xts_compare \
  --base-label baseline \
  --target-label candidate
```

### Option Reference

#### Inputs And Compare Mode Selection

- `PATH`
  Positional run archives or a results directory.
  Common behavior in practice:
  `1` path -> single-run summary or directory auto-discovery,
  `2` paths -> compare mode.
- `--base PATH`
  Explicit base run archive or extracted result directory.
- `--target PATH`
  Explicit target run archive or extracted result directory. Required with `--base`.
- `--timeline PATH [PATH ...]`
  Two or more runs for timeline mode.
- `--base-label LABEL`
  Resolve the base run from the selector run store by label.
- `--target-label LABEL`
  Resolve the target run from the selector run store by label.
- `--label-root PATH`
  Override the selector run-store root used with `--base-label` and `--target-label`.
- `--selector-report FILE`
  Correlate compare output with a selector JSON report.
- `--labels LABELS`
  Comma-separated display labels for compare or timeline output.

#### Output Format

- `--json`
  Emit JSON instead of terminal text.
- `--html`
  Emit a standalone HTML report.
- `--markdown`
  Emit Markdown instead of terminal text.
- `-o FILE`, `--output FILE`
  Write the selected output to a file instead of stdout.

#### Filtering And Report Focus

- `--module-filter GLOB`
  Restrict terminal output to modules matching a glob.
- `--suite-filter GLOB`
  Restrict terminal output to suites matching a glob.
- `--case-filter GLOB`
  Restrict terminal output to test cases matching a glob.
- `--failure-type TYPES`
  Comma-separated failure-type filter for terminal output.
  Supported values: `crash`, `timeout`, `assertion`, `cast`, `resource`, `unknown`.
- `--sort module|severity|time-delta`
  Sort key for terminal compare output.
- `--min-time-delta MS`
  Minimum absolute timing delta for performance-change reporting.
- `--min-time-ratio RATIO`
  Minimum relative timing ratio for performance-change reporting.
- `--show-stable`
  Include `STABLE_PASS` cases in terminal output.
- `--show-stable-blocked`
  Include `STABLE_BLOCKED` cases in terminal output.
- `--show-persistent`
  Include the `PERSISTENT_FAIL` details section in terminal output.
- `--regressions-only`
  Show the summary plus the `REGRESSION` section only.

#### Directory Scan And Archive Safety

- `--scan-recursive`
  Search subdirectories recursively when the input is a results directory.
- `--scan-glob GLOB`
  Limit discovered archives to names or relative paths matching a glob.
- `--scan-limit N`
  Keep only the newest `N` discovered archives after ordering. `0` means unlimited.
- `--strict-archive`
  Reject archives with skipped special entries instead of reporting them as notices.

### Common Examples

Compare two archives:

```bash
python3 -m arkui_xts_selector.xts_compare base.zip target.zip
```

Export HTML:

```bash
python3 -m arkui_xts_selector.xts_compare base.zip target.zip --html -o report.html
```

Export Markdown:

```bash
python3 -m arkui_xts_selector.xts_compare base.zip target.zip --markdown -o report.md
```

Focus on regressions only:

```bash
python3 -m arkui_xts_selector.xts_compare base.zip target.zip --regressions-only
```

Inspect a results directory:

```bash
python3 -m arkui_xts_selector.xts_compare /path/to/results-dir/
```

Scan nested directories with filters:

```bash
python3 -m arkui_xts_selector.xts_compare \
  /path/to/results-dir/ \
  --scan-recursive \
  --scan-glob "device-a/*.zip" \
  --scan-limit 5
```

Correlate actual regressions with selector predictions:

```bash
python3 -m arkui_xts_selector.xts_compare \
  base.zip target.zip \
  --selector-report arkui_xts_selector_report.json
```
