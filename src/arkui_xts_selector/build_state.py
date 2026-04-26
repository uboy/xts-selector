from __future__ import annotations

import hashlib
import shlex
from datetime import datetime
from pathlib import Path
from typing import Any

from .hdc_transport import build_hdc_command, build_hdc_env, build_hdc_shell_command, ensure_hdc_wrapper


def compact_token(value: str) -> str:
    return "".join(ch for ch in value.lower() if ch.isalnum())


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def _xdevice_bootstrap_dir(root: Path) -> Path:
    digest = hashlib.sha256(str(root.resolve()).encode("utf-8")).hexdigest()[:12]
    return (Path("/tmp") / "arkui_xts_selector_xdevice" / digest).resolve()


def discover_bundled_xdevice_packages(root: Path) -> list[Path]:
    candidates: list[Path] = []
    seen: set[str] = set()
    bases = [root, *list(root.parents[:4])]
    for base in bases:
        tools_dir = base / "tools"
        if not tools_dir.is_dir():
            continue
        for package in sorted(tools_dir.glob("xdevice*.tar.gz")):
            resolved = package.resolve()
            key = str(resolved)
            if key in seen:
                continue
            seen.add(key)
            candidates.append(resolved)

    def sort_key(path: Path) -> tuple[int, str]:
        name = path.name.lower()
        if name.startswith("xdevice-"):
            return (0, name)
        if "ohos" in name:
            return (1, name)
        if "devicetest" in name:
            return (2, name)
        return (3, name)

    return sorted(candidates, key=sort_key)


def build_bootstrap_xdevice_runner(root: Path) -> str | None:
    packages = discover_bundled_xdevice_packages(root)
    if not packages:
        return None
    bootstrap_dir = _xdevice_bootstrap_dir(root)
    home_dir = bootstrap_dir / "home"
    bootstrap_dir_q = shlex.quote(str(bootstrap_dir))
    bootstrap_pkg_dir_q = shlex.quote(str(bootstrap_dir / "xdevice"))
    home_dir_q = shlex.quote(str(home_dir))
    package_args = " ".join(shlex.quote(str(path)) for path in packages)
    return (
        f"mkdir -p {bootstrap_dir_q} {home_dir_q} && "
        f"if [ ! -d {bootstrap_pkg_dir_q} ]; then "
        f"python3 -m pip install --no-deps --disable-pip-version-check --target {bootstrap_dir_q} {package_args}; "
        f"fi && HOME={home_dir_q} PYTHONPATH={bootstrap_dir_q} python3 -m xdevice"
    )


def build_aa_test_command(
    bundle_name: str | None,
    module_name: str | None,
    project_path: str,
    device: str | None,
    hdc_path: Path | str | None = None,
    hdc_endpoint: str | None = None,
) -> str | None:
    if not bundle_name:
        return None
    is_static = "static" in compact_token(project_path)
    if is_static:
        return build_hdc_shell_command(
            ["shell", "aa", "test", "-b", bundle_name, "-m", module_name or "entry", "-s", "unittest", "OpenHarmonyTestRunner"],
            hdc_path=hdc_path,
            hdc_endpoint=hdc_endpoint,
            device=device,
        )
    return build_hdc_shell_command(
        ["shell", "aa", "test", "-p", bundle_name, "-b", bundle_name, "-s", "unittest", "OpenHarmonyTestRunner"],
        hdc_path=hdc_path,
        hdc_endpoint=hdc_endpoint,
        device=device,
    )


def find_hap_for_module(
    module_name: str | None,
    acts_out_root: Path | None,
) -> Path | None:
    if not module_name or not acts_out_root:
        return None
    tc_dir = acts_out_root / "testcases"
    if not tc_dir.is_dir():
        return None
    compact = compact_token(module_name)
    candidates: list[Path] = []
    for hap in sorted(tc_dir.glob("*.hap")):
        hap_stem = compact_token(hap.stem)
        if hap_stem == compact or compact in hap_stem:
            candidates.append(hap)
    if not candidates:
        for hap in sorted(tc_dir.glob("**/*.hap")):
            hap_stem = compact_token(hap.stem)
            if hap_stem == compact or compact in hap_stem:
                candidates.append(hap)
    if len(candidates) == 1:
        return candidates[0]
    for hap in candidates:
        if compact_token(hap.stem) == compact:
            return hap
    return candidates[0] if candidates else None


def build_hdc_install_command(
    bundle_name: str | None,
    module_name: str | None,
    acts_out_root: Path | None,
    hdc_path: Path | str | None = None,
    hdc_endpoint: str | None = None,
    device: str | None = None,
) -> str | None:
    if not bundle_name:
        return None
    hap_path = find_hap_for_module(module_name, acts_out_root)
    if not hap_path:
        return None
    args = build_hdc_command(
        ["install", str(hap_path)],
        hdc_path=hdc_path,
        hdc_endpoint=hdc_endpoint,
        device=device,
    )
    from .hdc_transport import render_shell_command, render_hdc_env_prefix
    return f"{render_hdc_env_prefix(hdc_path)}{render_shell_command(args)}"


def build_uninstall_bundle_shell_command(
    bundle_name: str,
    *,
    hdc_path: Path | str | None = None,
    hdc_endpoint: str | None = None,
    device: str | None = None,
) -> str:
    """Return an ``hdc shell bm uninstall`` command for the given bundle id."""
    name = str(bundle_name or "").strip()
    if not name:
        return ""
    return build_hdc_shell_command(
        ["shell", "bm", "uninstall", "-n", name],
        hdc_path=hdc_path,
        hdc_endpoint=hdc_endpoint,
        device=device,
    )


def build_install_test_haps_shell_sequence(
    local_haps: list[Path],
    *,
    hdc_path: Path | str | None = None,
    hdc_endpoint: str | None = None,
    device: str | None = None,
) -> list[str]:
    """Return hdc shell commands to push each HAP to the device and run ``bm install``."""
    commands: list[str] = []
    for local in local_haps:
        if not local.is_file():
            continue
        remote = f"/data/local/tmp/{local.name}"
        commands.append(
            build_hdc_shell_command(
                ["file", "send", str(local.resolve()), remote],
                hdc_path=hdc_path,
                hdc_endpoint=hdc_endpoint,
                device=device,
            )
        )
        commands.append(
            build_hdc_shell_command(
                ["shell", "bm", "install", "-p", remote],
                hdc_path=hdc_path,
                hdc_endpoint=hdc_endpoint,
                device=device,
            )
        )
    return commands


def _safe_report_fragment(value: str | None) -> str:
    raw = str(value or "").strip().lower()
    compact = "".join(ch if ch.isalnum() else "-" for ch in raw)
    compact = "-".join(part for part in compact.split("-") if part)
    return compact or "report"


def build_xdevice_command(
    repo_root: Path,
    module_name: str | None,
    device: str | None,
    acts_out_root: Path | None,
    report_path: Path | None = None,
    hdc_path: Path | str | None = None,
    hdc_endpoint: str | None = None,
) -> str | None:
    if not module_name:
        return None
    root = acts_out_root or (repo_root / "out/release/suites/acts")
    tc_path = root / "testcases"
    res_path = root / "resource"
    if report_path is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_path_value = root / "xdevice_reports" / f"{timestamp}_{_safe_report_fragment(module_name)}"
    else:
        report_path_value = report_path
    args = [
        "run",
        "acts",
        "-tcpath",
        str(tc_path),
        "-rp",
        str(report_path_value),
        "-l",
        module_name,
    ]
    if res_path.exists():
        args.extend(["-respath", str(res_path)])
    if device:
        args.extend(["-sn", device])
    runner = build_bootstrap_xdevice_runner(root) or "python3 -m xdevice"
    if runner == "python3 -m xdevice" and (root / "run.sh").exists():
        runner = "bash ./run.sh"
    rendered_args = " ".join(shlex.quote(arg) for arg in args)
    wrapper_dir = ensure_hdc_wrapper(root, hdc_path=hdc_path, hdc_endpoint=hdc_endpoint)
    env_prefix = ""
    if wrapper_dir is not None:
        env_prefix = f"PATH={shlex.quote(str(wrapper_dir))}:$PATH "
    return f"cd {shlex.quote(str(root))} && {env_prefix}{runner} {rendered_args}"


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
    product_name = getattr(app_config, "product_name", None) or "rk3568"
    system_size = getattr(app_config, "system_size", None) or "standard"
    xts_suitetype = getattr(app_config, "xts_suitetype", None)
    prebuilt_ready = bool(getattr(app_config, "daily_prebuilt_ready", False))
    prebuilt_note = getattr(app_config, "daily_prebuilt_note", "") or ""
    full_code_build_command = f"./build.sh --product-name {product_name} --ccache"
    acts_base = f"./test/xts/acts/build.sh product_name={product_name} system_size={system_size}"
    if xts_suitetype:
        acts_base = f"{acts_base} xts_suitetype={xts_suitetype}"

    needs_code_build = product_build.get("status") in {"missing", "failed", "partial", "unknown"} and not prebuilt_ready
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
        if prebuilt_note:
            reasons.append(prebuilt_note)
        else:
            reasons.append("Built ACTS artifacts were not found under acts_out_root.")

    return {
        "required": True,
        "reason": " ".join(reasons),
        "preparation_required": needs_code_build or needs_acts_build,
        "code_build_required": needs_code_build,
        "acts_build_required": needs_acts_build,
        "full_code_build_command": full_code_build_command,
        "full_acts_build_command": acts_base,
        "target_build_commands": target_commands,
    }
