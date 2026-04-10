from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def load_json(path: Path) -> dict:
    text = read_text(path)
    if not text:
        return {}
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {}


def parse_module_info(module_info_path: Path) -> list[str]:
    text = read_text(module_info_path)
    if not text:
        return []
    entries: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        entries.append(line)
    return entries


def inspect_built_artifacts(repo_root: Path, acts_out_root: Path | None) -> dict:
    root = acts_out_root or (repo_root / "out/release/suites/acts")
    testcases_dir = root / "testcases"
    module_info = testcases_dir / "module_info.list"
    json_paths = sorted(testcases_dir.glob('*.json')) if testcases_dir.exists() else []
    module_entries = parse_module_info(module_info) if module_info.exists() else []
    return {
        "acts_out_root": str(root),
        "testcases_dir_exists": testcases_dir.exists(),
        "module_info_exists": module_info.exists(),
        "testcase_json_count": len(json_paths),
        "module_info_entry_count": len(module_entries),
        "status": "built" if testcases_dir.exists() and module_info.exists() else "missing",
    }


def load_built_artifact_index(repo_root: Path, acts_out_root: Path | None) -> dict:
    root = acts_out_root or (repo_root / "out/release/suites/acts")
    testcases_dir = root / "testcases"
    module_info = testcases_dir / "module_info.list"
    if not testcases_dir.exists():
        return {
            "status": "missing",
            "testcase_modules_count": 0,
            "hap_runtime_modules_count": 0,
            "testcase_modules": [],
            "hap_runtime_modules": [],
        }

    testcase_modules: list[dict] = []
    hap_runtime_modules: dict[str, dict] = {}
    for json_path in sorted(testcases_dir.glob('*.json')):
        data = load_json(json_path)
        if not isinstance(data, dict):
            continue
        driver = data.get('driver', {}) if isinstance(data.get('driver'), dict) else {}
        test_file_names: list[str] = []
        for kit in data.get('kits', []):
            if not isinstance(kit, dict):
                continue
            names = kit.get('test-file-name', [])
            if isinstance(names, list):
                test_file_names.extend([item for item in names if isinstance(item, str)])
        testcase_modules.append({
            "json": str(json_path),
            "bundle_name": driver.get('bundle-name'),
            "driver_module_name": driver.get('module-name'),
            "driver_type": driver.get('type'),
            "test_file_names": test_file_names,
        })
        for name in test_file_names:
            if not name.endswith('.hap'):
                continue
            stem = Path(name).stem
            hap_runtime_modules[stem] = {
                "hap": name,
                "stem": stem,
                "source_json": str(json_path),
                "bundle_name": driver.get('bundle-name'),
                "driver_module_name": driver.get('module-name'),
            }

    module_entries = parse_module_info(module_info) if module_info.exists() else []
    return {
        "status": "built" if module_info.exists() else "partial",
        "acts_out_root": str(root),
        "module_info_entries": module_entries,
        "testcase_modules_count": len(testcase_modules),
        "hap_runtime_modules_count": len(hap_runtime_modules),
        "testcase_modules": testcase_modules,
        "hap_runtime_modules": sorted(hap_runtime_modules.values(), key=lambda item: item['stem']),
    }


def _normalized_artifact_token(value: object) -> str:
    return "".join(ch for ch in str(value or "").lower() if ch.isalnum())


def _artifact_identifier_set(values: list[object]) -> set[str]:
    return {
        token
        for token in (_normalized_artifact_token(value) for value in values)
        if token
    }


def resolve_test_hap_names_from_artifact_index(
    target: dict[str, Any],
    built_artifact_index: dict[str, Any] | None,
) -> tuple[list[str], str]:
    """Infer ``test-file-name`` HAP basenames from built ``testcases/*.json`` when the repo ``Test.json`` omits them.

    Matching uses the same normalization as :func:`resolve_target_artifact_availability` so
    ``bundle_name`` lines up with the deployed ACTS metadata even when the source tree is stale.

    Returns ``(hap_basenames, provenance)`` with ``provenance`` empty when nothing was inferred.
    """
    if not isinstance(built_artifact_index, dict):
        return [], ""
    modules = built_artifact_index.get("testcase_modules")
    if not isinstance(modules, list):
        modules = []
    hap_runtime = built_artifact_index.get("hap_runtime_modules")
    if not isinstance(hap_runtime, list):
        hap_runtime = []
    if not modules and not hap_runtime:
        return [], ""

    bundle = str(target.get("bundle_name") or "").strip()
    if bundle:
        want = _normalized_artifact_token(bundle)
        if want:
            collected: list[str] = []
            seen: set[str] = set()
            for mod in modules:
                if not isinstance(mod, dict):
                    continue
                mod_bundle = str(mod.get("bundle_name") or "").strip()
                if _normalized_artifact_token(mod_bundle) != want:
                    continue
                for name in mod.get("test_file_names") or []:
                    if not isinstance(name, str) or not name.endswith(".hap"):
                        continue
                    if name not in seen:
                        seen.add(name)
                        collected.append(name)
            if collected:
                return collected, "acts_testcases_index:bundle_name"

    xdm = str(target.get("xdevice_module_name") or "").strip()
    if xdm:
        want_stem = _normalized_artifact_token(xdm)
        if want_stem:
            for item in hap_runtime:
                if not isinstance(item, dict):
                    continue
                if _normalized_artifact_token(item.get("stem")) != want_stem:
                    continue
                hap = item.get("hap")
                if isinstance(hap, str) and hap.endswith(".hap"):
                    return [hap], "acts_testcases_index:hap_stem"

    return [], ""


def resolve_target_artifact_availability(target: dict[str, Any], built_artifact_index: dict[str, Any] | None) -> dict[str, str]:
    index = built_artifact_index if isinstance(built_artifact_index, dict) else {}
    testcase_modules = index.get("testcase_modules", [])
    module_info_entries = index.get("module_info_entries", [])
    hap_runtime_modules = index.get("hap_runtime_modules", [])
    testcase_count = int(index.get("testcase_modules_count", 0) or 0)
    hap_count = int(index.get("hap_runtime_modules_count", 0) or 0)
    has_verifiable_inventory = bool(testcase_modules or module_info_entries or hap_runtime_modules or testcase_count or hap_count)

    if not has_verifiable_inventory:
        return {
            "status": "unknown",
            "reason": "current ACTS artifacts are unavailable, so suite availability could not be verified",
            "matched_by": "",
        }

    available_tokens: dict[str, set[str]] = {
        "module_info.list": _artifact_identifier_set(module_info_entries if isinstance(module_info_entries, list) else []),
        "driver_module_name": _artifact_identifier_set(
            [item.get("driver_module_name") for item in testcase_modules if isinstance(item, dict)]
        ),
        "bundle_name": _artifact_identifier_set(
            [item.get("bundle_name") for item in testcase_modules if isinstance(item, dict)]
        ),
        "testcase_json": _artifact_identifier_set(
            [Path(str(item.get("json") or "")).stem for item in testcase_modules if isinstance(item, dict)]
        ),
        "hap_runtime": _artifact_identifier_set(
            [item.get("stem") for item in hap_runtime_modules if isinstance(item, dict)]
        ),
    }

    candidate_tokens = [
        ("build_target", target.get("build_target")),
        ("xdevice_module_name", target.get("xdevice_module_name")),
        ("driver_module_name", target.get("driver_module_name")),
        ("bundle_name", target.get("bundle_name")),
        ("test_json", Path(str(target.get("test_json") or "")).stem),
        ("project", Path(str(target.get("project") or "")).name),
    ]
    for name in target.get("test_haps", []) or []:
        candidate_tokens.append(("test_hap", Path(str(name)).stem))

    normalized_candidates = [
        (kind, str(value or ""), _normalized_artifact_token(value))
        for kind, value in candidate_tokens
        if str(value or "").strip()
    ]

    for candidate_kind, candidate_value, candidate_token in normalized_candidates:
        if not candidate_token:
            continue
        for available_kind, tokens in available_tokens.items():
            if candidate_token in tokens:
                return {
                    "status": "available",
                    "reason": f"verified in active ACTS artifacts via {available_kind}: {candidate_value}",
                    "matched_by": f"{candidate_kind}->{available_kind}",
                }

    suite_name = (
        str(target.get("build_target") or "")
        or str(target.get("xdevice_module_name") or "")
        or str(target.get("project") or "")
        or str(target.get("test_json") or "")
    )
    return {
        "status": "missing",
        "reason": f"not found in the current ACTS artifacts inventory: {suite_name}",
        "matched_by": "",
    }
