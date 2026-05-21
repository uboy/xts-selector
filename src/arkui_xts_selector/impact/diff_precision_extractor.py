"""Git diff to precision evidence extractor (Phase H Track D).

Parses ``git diff --unified=0`` output to derive changed line ranges and
touched symbols per file, so that ``--from-git-diff BASE_REV`` can feed
the Phase F precision pipeline automatically.

Design constraints
------------------
* No must_run produced — this is additive evidence feeding PrecisionResolver.
* Graceful degradation: git not found, bad ref, or empty diff → returns empty
  list with ``git_unavailable`` / ``invalid_ref`` reason; never crashes.
* No direct file→test hardcoding.
* subprocess.run with explicit args list (no shell=True) — safe for untrusted refs
  that go through validation before passing to git.
* Import boundary: standard library + symbol_span_index only.
"""
from __future__ import annotations

import re
import subprocess
import sys
from typing import Optional

from arkui_xts_selector.impact.symbol_span_index import SymbolSpanIndex

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

_HUNK_HEADER_RE = re.compile(
    r"^@@ -\d+(?:,\d+)? \+(?P<start>\d+)(?:,(?P<count>\d+))? @@"
)
_FILE_HEADER_RE = re.compile(r"^\+\+\+ b/(?P<path>.+)$")
_NO_NEWLINE_MARKER = "\\ No newline at end of file"


def extract_precision_from_git_diff(
    base_rev: str,
    head_rev: str = "HEAD",
    repo_path: str = ".",
) -> list[dict]:
    """Extract per-file precision evidence from a git diff.

    Runs ``git diff --unified=0 <base_rev>..<head_rev>`` in ``repo_path``,
    parses hunk headers to derive line ranges for each modified file, and
    calls ``SymbolSpanIndex.find_touched_symbols()`` to derive touched symbols.

    Parameters
    ----------
    base_rev:
        Base git revision (commit hash, branch, tag, or ``HEAD~N``).
    head_rev:
        Head git revision.  Defaults to ``"HEAD"``.
    repo_path:
        Working directory for the git command.  Defaults to current directory.

    Returns
    -------
    list[dict]
        Each entry has the shape::

            {
                "path": str,
                "changed_lines": [(start, end), ...],   # 1-based, inclusive
                "changed_symbols": [str, ...],
                "unresolved_reasons": [str, ...],        # empty on success
            }

        Returns an empty list on error; callers should check ``unresolved_reasons``
        on individual entries or inspect the ``git_unavailable`` / ``invalid_ref``
        sentinel value in the returned list.

    Notes
    -----
    * Additions-only hunks (``+0,N``) are ignored — line 0 deletions are not
      meaningful for the new-file side.
    * The function never raises; all errors are captured as ``unresolved_reasons``.
    """
    diff_text, error_reason = _run_git_diff(base_rev, head_rev, repo_path)
    if error_reason:
        return [
            {
                "path": "",
                "changed_lines": [],
                "changed_symbols": [],
                "unresolved_reasons": [error_reason],
            }
        ]

    if not diff_text.strip():
        return []

    return _parse_diff(diff_text)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _run_git_diff(
    base_rev: str,
    head_rev: str,
    repo_path: str,
) -> tuple[str, str]:
    """Run git diff and return (stdout, error_reason).

    Returns (output, "") on success, ("", reason) on failure.
    """
    # Basic sanitisation: refs must not contain shell metacharacters.
    # We use a list-form subprocess call (no shell=True) so injection is
    # already blocked, but this check gives a clear error message.
    if not _is_safe_rev(base_rev) or not _is_safe_rev(head_rev):
        return "", "invalid_ref"

    try:
        result = subprocess.run(
            ["git", "diff", "--unified=0", f"{base_rev}..{head_rev}"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except FileNotFoundError:
        return "", "git_unavailable"
    except subprocess.TimeoutExpired:
        return "", "git_timeout"
    except OSError:
        return "", "git_unavailable"

    if result.returncode != 0:
        stderr_lower = result.stderr.lower()
        if "unknown revision" in stderr_lower or "bad object" in stderr_lower:
            return "", "invalid_ref"
        if "not a git repository" in stderr_lower:
            return "", "git_unavailable"
        # Other non-zero exits (e.g. no diff on identical trees) — treat as empty.
        return "", "git_diff_error"

    return result.stdout, ""


def _is_safe_rev(rev: str) -> bool:
    """Return True if ``rev`` looks like a safe git revision identifier.

    Allows: alphanumeric, ``-``, ``_``, ``.``, ``/``, ``~``, ``^``, ``@``,
    ``{``, ``}``, ``:``.  Rejects spaces, newlines, semicolons, etc.
    """
    return bool(re.fullmatch(r"[\w.\-/~^@{}:]+", rev))


def _parse_diff(diff_text: str) -> list[dict]:
    """Parse unified diff output into per-file precision entries."""
    results: dict[str, dict] = {}  # path → entry
    current_path: Optional[str] = None

    for line in diff_text.splitlines():
        if line.startswith("+++ b/"):
            m = _FILE_HEADER_RE.match(line)
            if m:
                current_path = m.group("path")
                if current_path not in results:
                    results[current_path] = {
                        "path": current_path,
                        "changed_lines": [],
                        "changed_symbols": [],
                        "unresolved_reasons": [],
                    }
            continue

        if line.startswith("@@") and current_path:
            m = _HUNK_HEADER_RE.match(line)
            if m:
                start = int(m.group("start"))
                count_str = m.group("count")
                count = int(count_str) if count_str is not None else 1

                # count=0 means a pure deletion (no added lines); skip.
                if count == 0:
                    continue

                end = start + count - 1
                results[current_path]["changed_lines"].append((start, end))

    # Now derive touched symbols for each file.
    span_index = SymbolSpanIndex()
    entries: list[dict] = []

    for path, entry in results.items():
        ranges = entry["changed_lines"]
        if not ranges:
            entries.append(entry)
            continue

        all_symbols: set[str] = set()
        any_span_failure = False

        for start, end in ranges:
            touched, reasons = span_index.find_touched_symbols(path, start, end)
            for span in touched:
                all_symbols.add(span.symbol)
            if not touched and reasons:
                any_span_failure = True

        entry["changed_symbols"] = sorted(all_symbols)
        if any_span_failure and not all_symbols:
            entry["unresolved_reasons"].append("hunk_symbol_not_found")

        entries.append(entry)

    return entries
