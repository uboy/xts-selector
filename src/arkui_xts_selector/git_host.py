"""Git host API and PR resolution functions."""

from __future__ import annotations

import json
import re
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from configparser import ConfigParser
from pathlib import Path
from typing import Iterable

from .changed_files import (
    extract_patch_text_from_pr_file_item,
    merge_changed_ranges,
    normalize_changed_files,
    parse_unified_diff_changed_ranges,
)
from .constants import CODEHUB_SECTION_NAMES, GIT_HOST_KIND_CHOICES, PR_SOURCE_CHOICES
from .models import AppConfig
from .workspace import discover_repo_root, resolve_workspace_path


REPO_ROOT = discover_repo_root()


def resolve_path(value: str | None, default: Path, repo_root: Path) -> Path:
    """Resolve a path value relative to the repo root."""
    return resolve_workspace_path(value=value, default=default, repo_root=repo_root)


def normalize_git_host_kind(value: str | None) -> str:
    """Normalize git host kind to a canonical value."""
    normalized = str(value or "").strip().lower()
    if normalized in {"", "auto"}:
        return "auto"
    if normalized in {"gitcode"}:
        return "gitcode"
    if normalized in {"codehub", "codehub-y", "cr-y.codehub", "opencodehub"}:
        return "codehub"
    return normalized


def _load_ini_git_host_section(parser: ConfigParser, section: str) -> tuple[str | None, str | None]:
    """Load URL and token from a git host config section."""
    if not parser.has_section(section):
        return None, None
    normalized_kind = normalize_git_host_kind(section)
    option_names: list[str]
    if normalized_kind == "gitcode":
        option_names = ["gitcode-url", "url"]
    elif normalized_kind == "codehub":
        option_names = [f"{section}-url", "codehub-url", "url"]
    else:
        option_names = ["url"]
    url = next((parser.get(section, option, fallback=None) for option in option_names if parser.has_option(section, option)), None)
    token = parser.get(section, "token", fallback=None)
    return url, token


def load_ini_git_host_config(path_value: str | None, repo_root: Path, host_kind: str) -> tuple[str | None, str | None]:
    """Load git host API credentials from an INI config file."""
    if not path_value:
        return None, None
    path = resolve_path(path_value, repo_root, repo_root)
    if not path.exists():
        return None, None
    parser = ConfigParser()
    parser.read(path, encoding="utf-8-sig")
    normalized_kind = normalize_git_host_kind(host_kind)
    if normalized_kind == "gitcode":
        sections_to_try = ("gitcode",)
    elif normalized_kind == "codehub":
        sections_to_try = CODEHUB_SECTION_NAMES
    else:
        sections_to_try = ("gitcode", *CODEHUB_SECTION_NAMES)
    for section in sections_to_try:
        url, token = _load_ini_git_host_section(parser, section)
        if url or token:
            return url, token
    return None, None


def load_ini_gitcode_config(path_value: str | None, repo_root: Path) -> tuple[str | None, str | None]:
    """Load gitcode-specific API credentials from an INI config file."""
    return load_ini_git_host_config(path_value, repo_root, "gitcode")


def git_changed_files(repo_root: Path, diff_ref: str) -> list[Path]:
    """Get changed files from git diff."""
    command = ["git", "-C", str(repo_root), "diff", "--name-only", diff_ref]
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or "git diff failed")
    return normalize_changed_files(completed.stdout.splitlines(), base_roots=[repo_root])


def run_git(repo_root: Path, args: list[str]) -> subprocess.CompletedProcess:
    """Run a git command in the specified repo."""
    return subprocess.run(
        ["git", "-C", str(repo_root), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def parse_pr_number(pr_url: str) -> str:
    """Extract PR number from a URL or numeric string."""
    from urllib.parse import urlparse
    if pr_url.isdigit():
        return pr_url
    parsed = urlparse(pr_url)
    match = re.search(r"/(?:pulls?|merge_requests)/(\d+)", parsed.path)
    if not match:
        raise RuntimeError(f"could not parse PR number from URL: {pr_url}")
    return match.group(1)


def parse_owner_repo_from_pr(pr_ref: str) -> tuple[str, str] | None:
    """Extract owner/repo from a PR URL."""
    from urllib.parse import urlparse
    if pr_ref.isdigit():
        return None
    parsed = urlparse(pr_ref)
    match = re.search(r"/([^/]+)/([^/]+)/(?:pulls?|merge_requests)/\d+", parsed.path)
    if not match:
        return None
    return match.group(1), match.group(2)


def parse_owner_repo_from_remote_url(remote_url: str) -> tuple[str, str] | None:
    """Extract owner/repo from a git remote URL."""
    value = remote_url.strip()
    if not value:
        return None
    if value.endswith(".git"):
        value = value[:-4]
    if "://" in value:
        from urllib.parse import urlparse
        parsed = urlparse(value)
        parts = [part for part in parsed.path.split("/") if part]
    elif "@" in value and ":" in value:
        parts = [part for part in value.split(":", 1)[1].split("/") if part]
    else:
        parts = [part for part in value.split("/") if part]
    if len(parts) < 2:
        return None
    return parts[-2], parts[-1]


def discover_owner_repo_from_git_remote(repo_root: Path, remote: str) -> tuple[str, str] | None:
    """Discover owner/repo from git remote URL."""
    completed = run_git(repo_root, ["config", "--get", f"remote.{remote}.url"])
    if completed.returncode != 0:
        return None
    return parse_owner_repo_from_remote_url(completed.stdout.strip())


def resolve_pr_owner_repo(pr_ref: str, repo_root: Path, remote: str) -> tuple[str, str] | None:
    """Resolve owner/repo from PR URL or git remote."""
    return parse_owner_repo_from_pr(pr_ref) or discover_owner_repo_from_git_remote(repo_root, remote)


def fetch_pr_changed_files(repo_root: Path, remote: str, base_branch: str, pr_ref: str) -> list[Path]:
    """Fetch PR changed files using git."""
    pr_number = parse_pr_number(pr_ref)
    base_ref = f"refs/tmp/arkui_xts_selector/pr/{pr_number}/base"
    head_ref = f"refs/tmp/arkui_xts_selector/pr/{pr_number}/head"
    base_specs = [
        f"refs/heads/{base_branch}:{base_ref}",
        f"{base_branch}:{base_ref}",
    ]
    fetch_specs = [
        f"refs/pull/{pr_number}/head:{head_ref}",
        f"pull/{pr_number}/head:{head_ref}",
        f"refs/merge-requests/{pr_number}/head:{head_ref}",
    ]
    last_error = "unknown fetch error"
    base_ready = False
    for base_spec in base_specs:
        completed = run_git(repo_root, ["fetch", "--depth=400", remote, base_spec])
        if completed.returncode == 0:
            base_ready = True
            break
        last_error = completed.stderr.strip() or completed.stdout.strip() or last_error
    if not base_ready:
        raise RuntimeError(last_error)
    for spec in fetch_specs:
        completed = run_git(repo_root, ["fetch", "--depth=400", remote, spec])
        if completed.returncode == 0:
            diff = run_git(repo_root, ["diff", "--name-only", f"{base_ref}...{head_ref}"])
            if diff.returncode != 0:
                raise RuntimeError(diff.stderr.strip() or "git diff failed")
            return normalize_changed_files(diff.stdout.splitlines(), base_roots=[repo_root])
        last_error = completed.stderr.strip() or completed.stdout.strip() or last_error
    raise RuntimeError(last_error)


def infer_git_host_kind(
    pr_ref: str,
    *,
    configured_kind: str | None = None,
    api_url: str | None = None,
) -> str:
    """Infer git host kind from PR URL or API URL."""
    from urllib.parse import urlparse
    normalized_kind = normalize_git_host_kind(configured_kind)
    if normalized_kind != "auto":
        return normalized_kind

    parsed_pr = urlparse(pr_ref) if not str(pr_ref).isdigit() else None
    if parsed_pr is not None:
        pr_host = parsed_pr.netloc.lower()
        pr_path = parsed_pr.path.lower()
        if "codehub" in pr_host:
            return "codehub"
        if "gitcode" in pr_host:
            return "gitcode"
        if "/merge_requests/" in pr_path:
            return "codehub"
        if re.search(r"/pulls?/\d+", pr_path):
            return "gitcode"

    parsed_api = urlparse(api_url or "")
    api_host = parsed_api.netloc.lower()
    if "codehub" in api_host:
        return "codehub"
    if "gitcode" in api_host:
        return "gitcode"
    return "gitcode"


def resolve_pr_api_credentials(app_config: AppConfig, pr_ref: str) -> tuple[str, str | None, str | None]:
    """Resolve PR API credentials from config."""
    host_kind = infer_git_host_kind(
        pr_ref,
        configured_kind=app_config.git_host_kind,
        api_url=app_config.git_host_api_url or app_config.gitcode_api_url,
    )
    api_url = app_config.git_host_api_url or app_config.gitcode_api_url
    token = app_config.git_host_token or app_config.gitcode_token
    if (not api_url or not token) and app_config.git_host_config_path:
        ini_url, ini_token = load_ini_git_host_config(
            str(app_config.git_host_config_path),
            app_config.repo_root,
            host_kind,
        )
        api_url = api_url or ini_url
        token = token or ini_token
    return host_kind, api_url, token


def fetch_git_host_api_json(api_kind: str, api_url: str, token: str, api_path: str | Iterable[str]) -> object:
    """Fetch JSON from a git host API."""
    base = api_url.rstrip("/")
    api_paths = [api_path] if isinstance(api_path, str) else [str(item) for item in api_path if str(item)]
    last_error = f"{api_kind} api failed"
    for candidate_path in api_paths:
        requests_to_try: list[urllib.request.Request]
        if api_kind == "gitcode":
            separator = "&" if "?" in candidate_path else "?"
            requests_to_try = [
                urllib.request.Request(
                    f"{base}{candidate_path}{separator}{urllib.parse.urlencode({'access_token': token})}",
                    headers={"Accept": "application/json"},
                ),
                urllib.request.Request(
                    f"{base}{candidate_path}",
                    headers={"Accept": "application/json", "private-token": token},
                ),
            ]
        else:
            requests_to_try = [
                urllib.request.Request(
                    f"{base}{candidate_path}",
                    headers={"Accept": "application/json", "Private-Token": token},
                ),
            ]
        path_missing = True
        for request in requests_to_try:
            try:
                with urllib.request.urlopen(request, timeout=20) as response:
                    return json.loads(response.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                last_error = f"{api_kind} api failed: {exc}"
                path_missing = path_missing and exc.code in {404, 410}
            except urllib.error.URLError as exc:
                last_error = f"{api_kind} api failed: {exc}"
                path_missing = False
            except json.JSONDecodeError as exc:
                last_error = f"{api_kind} api returned invalid json: {exc}"
                path_missing = False
        if not path_missing:
            break
    raise RuntimeError(last_error)


def fetch_pr_metadata_via_api(api_kind: str, api_url: str, token: str, owner: str, repo: str, pr_ref: str) -> dict:
    """Fetch PR metadata from git host API."""
    pr_number = parse_pr_number(pr_ref)
    if api_kind == "codehub":
        project_id = urllib.parse.quote(f"{owner}/{repo}", safe="")
        api_path: str | list[str] = [
            f"/api/v4/projects/{project_id}/isource/merge_requests/{pr_number}",
            f"/api/v4/projects/{project_id}/merge_requests/{pr_number}",
        ]
    else:
        api_path = f"/api/v5/repos/{owner}/{repo}/pulls/{pr_number}"
    data = fetch_git_host_api_json(api_kind, api_url, token, api_path)
    if not isinstance(data, dict):
        raise RuntimeError(f"{api_kind} api unexpected PR response: {data}")
    return data


def fetch_pr_changed_files_via_api(
    api_kind: str,
    api_url: str,
    token: str,
    owner: str,
    repo: str,
    pr_ref: str,
    repo_root: Path,
) -> list[Path]:
    """Fetch PR changed files from git host API."""
    changed_files, _changed_ranges = fetch_pr_changed_files_and_ranges_via_api(
        api_kind=api_kind,
        api_url=api_url,
        token=token,
        owner=owner,
        repo=repo,
        pr_ref=pr_ref,
        repo_root=repo_root,
    )
    return changed_files


def fetch_pr_changed_files_and_ranges_via_api(
    api_kind: str,
    api_url: str,
    token: str,
    owner: str,
    repo: str,
    pr_ref: str,
    repo_root: Path,
) -> tuple[list[Path], dict[Path, list[tuple[int, int]]]]:
    """Fetch PR changed files and line ranges from git host API."""
    pr_number = parse_pr_number(pr_ref)
    changed_files: list[Path] = []
    changed_ranges_by_file: dict[Path, list[tuple[int, int]]] = {}

    def _append_item(path_value: str | None, item: dict[str, object]) -> None:
        if not path_value:
            return
        normalized_paths = normalize_changed_files([path_value], base_roots=[repo_root])
        if not normalized_paths:
            return
        normalized_path = normalized_paths[0]
        changed_files.append(normalized_path)
        patch_text = extract_patch_text_from_pr_file_item(item)
        parsed_ranges = parse_unified_diff_changed_ranges(patch_text)
        if parsed_ranges:
            resolved_path = normalized_path.resolve()
            changed_ranges_by_file[resolved_path] = merge_changed_ranges(
                list(changed_ranges_by_file.get(resolved_path, [])) + parsed_ranges
            )

    if api_kind == "codehub":
        project_id = urllib.parse.quote(f"{owner}/{repo}", safe="")
        data = fetch_git_host_api_json(
            api_kind,
            api_url,
            token,
            [
                f"/api/v4/projects/{project_id}/isource/merge_requests/{pr_number}/changes",
                f"/api/v4/projects/{project_id}/merge_requests/{pr_number}/changes",
            ],
        )
        if isinstance(data, dict):
            data = data.get("changes") or data.get("files") or data.get("data") or data.get("changed_files")
        if not isinstance(data, list):
            raise RuntimeError(f"{api_kind} api unexpected response: {data}")
        for item in data:
            if not isinstance(item, dict):
                continue
            _append_item(
                item.get("new_path") or item.get("old_path") or item.get("filename"),
                item,
            )
    else:
        data = fetch_git_host_api_json(api_kind, api_url, token, f"/api/v5/repos/{owner}/{repo}/pulls/{pr_number}/files")
        if isinstance(data, dict):
            data = data.get("files") or data.get("data") or data.get("changed_files")
        if not isinstance(data, list):
            raise RuntimeError(f"{api_kind} api unexpected response: {data}")
        for item in data:
            if not isinstance(item, dict):
                continue
            _append_item(
                item.get("filename") or item.get("new_path") or item.get("old_path"),
                item,
            )

    deduped_files: list[Path] = []
    seen_paths: set[Path] = set()
    for changed_file in changed_files:
        resolved = changed_file.resolve()
        if resolved in seen_paths:
            continue
        deduped_files.append(changed_file)
        seen_paths.add(resolved)
    return deduped_files, changed_ranges_by_file


def resolve_pr_changed_files_with_ranges(
    app_config: AppConfig,
    pr_ref: str,
    pr_source: str,
) -> tuple[list[Path], dict[Path, list[tuple[int, int]]]]:
    """Resolve PR changed files and line ranges using API or git."""
    owner_repo = resolve_pr_owner_repo(pr_ref, app_config.git_repo_root, app_config.git_remote)
    api_error: RuntimeError | None = None
    if pr_source in ("auto", "api"):
        api_kind, api_url, token = resolve_pr_api_credentials(app_config, pr_ref)
        if not api_url or not token:
            api_error = RuntimeError(
                "PR API mode requires git host credentials; pass --git-host-token/--git-host-url or --git-host-config with [gitcode]/[codehub] token/url."
            )
        elif owner_repo is None:
            api_error = RuntimeError("could not determine owner/repo for PR API mode from --pr-url or local git remote")
        else:
            try:
                fetch_pr_metadata_via_api(
                    api_kind=api_kind,
                    api_url=api_url,
                    token=token,
                    owner=owner_repo[0],
                    repo=owner_repo[1],
                    pr_ref=pr_ref,
                )
                return fetch_pr_changed_files_and_ranges_via_api(
                    api_kind=api_kind,
                    api_url=api_url,
                    token=token,
                    owner=owner_repo[0],
                    repo=owner_repo[1],
                    pr_ref=pr_ref,
                    repo_root=app_config.git_repo_root,
                )
            except RuntimeError as exc:
                api_error = exc
        if pr_source == "api":
            raise api_error if api_error is not None else RuntimeError("PR API mode failed")

    try:
        return fetch_pr_changed_files(
            repo_root=app_config.git_repo_root,
            remote=app_config.git_remote,
            base_branch=app_config.git_base_branch,
            pr_ref=pr_ref,
        ), {}
    except RuntimeError as exc:
        if api_error is not None and pr_source == "auto":
            raise RuntimeError(f"api failed: {api_error}; git failed: {exc}") from exc
        raise


def resolve_pr_changed_files(app_config: AppConfig, pr_ref: str, pr_source: str) -> list[Path]:
    """Resolve PR changed files using API or git."""
    changed_files, _changed_ranges = resolve_pr_changed_files_with_ranges(app_config, pr_ref, pr_source)
    return changed_files
