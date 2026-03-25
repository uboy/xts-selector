from __future__ import annotations

import json
from pathlib import Path


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
        "module_info_entries": module_entries,
        "testcase_modules_count": len(testcase_modules),
        "hap_runtime_modules_count": len(hap_runtime_modules),
        "testcase_modules": testcase_modules,
        "hap_runtime_modules": sorted(hap_runtime_modules.values(), key=lambda item: item['stem']),
    }
