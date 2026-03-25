from __future__ import annotations

from pathlib import Path
from typing import Any


def compact_token(value: str) -> str:
    return "".join(ch for ch in value.lower() if ch.isalnum())


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def build_aa_test_command(bundle_name: str | None, module_name: str | None, project_path: str, device: str | None) -> str | None:
    if not bundle_name:
        return None
    prefix = "hdc shell "
    if device:
        prefix = f"hdc -t {device} shell "
    is_static = "static" in compact_token(project_path)
    if is_static:
        return f"{prefix}aa test -b {bundle_name} -m {module_name or 'entry'} -s unittest OpenHarmonyTestRunner"
    return f"{prefix}aa test -p {bundle_name} -b {bundle_name} -s unittest OpenHarmonyTestRunner"


def build_xdevice_command(repo_root: Path, module_name: str | None, device: str | None, acts_out_root: Path | None) -> str | None:
    if not module_name:
        return None
    root = acts_out_root or (repo_root / "out/release/suites/acts")
    tc_path = root / "testcases"
    res_path = root / "resource"
    report_path = root / "xdevice_reports/<timestamp>"
    args = [
        "run acts",
        f"-tcpath {tc_path}",
        f"-respath {res_path}",
        f"-rp {report_path}",
        f"-l {module_name}",
    ]
    if device:
        args.append(f"-sn {device}")
    return f"cd {root} && python -m xdevice \"{' '.join(args)}\""


def build_runtest_command(build_target: str, device: str | None) -> str | None:
    if not build_target:
        return None
    device_value = device or "<device-ip:port>"
    return f"./test/xts/acts/runtest.sh device={device_value} module={build_target} runonly=TRUE"


def infer_product_out_dir(repo_root: Path, product_name: str | None, acts_out_root: Path | None) -> Path | None:
    if product_name:
        return (repo_root / "out" / product_name).resolve()
    if acts_out_root:
        parts = list(acts_out_root.resolve().parts)
        if "out" in parts:
            index = parts.index("out")
            if index + 1 < len(parts):
                return Path(*parts[: index + 2])
    return None


def tail_text(path: Path, line_count: int = 80) -> str:
    text = read_text(path)
    if not text:
        return ""
    return "\n".join(text.splitlines()[-line_count:])


def inspect_product_build(repo_root: Path, product_name: str | None, acts_out_root: Path | None) -> dict:
    out_dir = infer_product_out_dir(repo_root, product_name, acts_out_root)
    if not out_dir:
        return {
            "status": "unknown",
            "reason": "Product out directory could not be inferred. Provide --product-name to enable full build diagnostics.",
        }

    build_log = out_dir / "build.log"
    error_log = out_dir / "error.log"
    ohos_ets_dir = out_dir / "ohos_ets"
    images_dir = out_dir / "images"
    build_tail = tail_text(build_log, 60)
    error_size = error_log.stat().st_size if error_log.exists() else 0

    status = "missing"
    reason = "No product build artifacts were found under the product out directory."
    if out_dir.exists() and not build_log.exists() and not error_log.exists():
        status = "partial"
        reason = "Product out directory exists, but no build.log/error.log was found."
    elif error_log.exists() and error_size > 0:
        status = "failed"
        reason = f"Product build failed; error.log exists and is non-empty ({error_size} bytes)."
    elif "COMPILE Failed!" in build_tail or "OHOSException" in build_tail:
        status = "failed"
        reason = "Product build log ends with a compile failure."
    elif out_dir.exists() and build_log.exists() and (images_dir.exists() or ohos_ets_dir.exists()):
        status = "present"
        reason = "Product build outputs are present; no failure marker was found in the inspected logs."

    return {
        "product_name": product_name,
        "out_dir": str(out_dir),
        "build_log": str(build_log),
        "error_log": str(error_log),
        "out_dir_exists": out_dir.exists(),
        "build_log_exists": build_log.exists(),
        "error_log_exists": error_log.exists(),
        "error_log_size": error_size,
        "ohos_ets_exists": ohos_ets_dir.exists(),
        "images_dir_exists": images_dir.exists(),
        "status": status,
        "reason": reason,
    }


def build_guidance(repo_root: Path, built_artifacts: dict, product_build: dict, app_config: Any, selected_build_targets: list[str]) -> dict | None:
    product_name = getattr(app_config, "product_name", None) or "<product_name>"
    system_size = getattr(app_config, "system_size", None) or "standard"
    xts_suitetype = getattr(app_config, "xts_suitetype", None)
    full_code_build_command = f"./build.sh --product-name {product_name} --ccache"
    acts_base = f"./test/xts/acts/build.sh product_name={product_name} system_size={system_size}"
    if xts_suitetype:
        acts_base = f"{acts_base} xts_suitetype={xts_suitetype}"

    needs_code_build = product_build.get("status") in {"missing", "failed", "partial", "unknown"}
    needs_acts_build = not (built_artifacts["testcases_dir_exists"] and built_artifacts["module_info_exists"])
    if not needs_code_build and not needs_acts_build:
        return None

    target_commands = [
        f"{acts_base} suite={target}"
        for target in sorted({item for item in selected_build_targets if item})[:10]
    ]
    reasons = []
    if needs_code_build:
        reasons.append(product_build.get("reason", "Product build is missing or failed."))
    if needs_acts_build:
        reasons.append("Built ACTS artifacts were not found under acts_out_root.")

    return {
        "required": True,
        "reason": " ".join(reasons),
        "code_build_required": needs_code_build,
        "acts_build_required": needs_acts_build,
        "full_code_build_command": full_code_build_command,
        "full_acts_build_command": acts_base,
        "target_build_commands": target_commands,
    }
