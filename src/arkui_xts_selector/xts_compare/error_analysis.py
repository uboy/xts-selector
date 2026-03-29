"""
Failure type classification and root cause clustering.

Classifies test failures into actionable categories (CRASH, TIMEOUT,
ASSERTION, etc.) and groups failures with the same normalized message
fingerprint into RootCauseCluster objects.
"""

from __future__ import annotations

import hashlib
import re
from collections import defaultdict

from .models import (
    CrashInfo,
    FailureType,
    RootCauseCluster,
    TestIdentity,
    TestOutcome,
    TestTransition,
)

# ---------------------------------------------------------------------------
# Failure type classification
# ---------------------------------------------------------------------------

# Pattern groups in priority order.  First match wins.
_CRASH_PATTERNS = [
    re.compile(r"App died", re.IGNORECASE),
    re.compile(r"SIGSEGV|SIGABRT|SIGBUS|SIGFPE|SIGILL", re.IGNORECASE),
    re.compile(r"cppcrash|jscrash|appfreeze", re.IGNORECASE),
    re.compile(r"Signal:\s*SIG", re.IGNORECASE),
    re.compile(r"Process\s+died|process\s+crash", re.IGNORECASE),
]

_TIMEOUT_PATTERNS = [
    re.compile(r"ShellCommandUnresponsiveException", re.IGNORECASE),
    re.compile(r"timed?\s*out", re.IGNORECASE),
    re.compile(r"unresponsive", re.IGNORECASE),
    re.compile(r"waited\s+\d+\s*(?:ms|s)\b", re.IGNORECASE),
]

_CAST_PATTERNS = [
    re.compile(r"cannot\s+be\s+cast\s+to", re.IGNORECASE),
    re.compile(r"type\s*mismatch", re.IGNORECASE),
    re.compile(r"is\s+not\s+a\s+function", re.IGNORECASE),
]

_ASSERTION_PATTERNS = [
    re.compile(r"expected\s+.+\s+but\s+got", re.IGNORECASE),
    re.compile(r"assert(?:True|False|Equal|NotEqual|Null|Undefined)", re.IGNORECASE),
    re.compile(r"expect\(.+\)\.(?:to|not)", re.IGNORECASE),
    re.compile(r"assertion\s+(?:failed|error)", re.IGNORECASE),
    re.compile(r"comparison\s+failed", re.IGNORECASE),
]

_RESOURCE_PATTERNS = [
    re.compile(r"out\s+of\s+memory|OOM\b", re.IGNORECASE),
    re.compile(r"no\s+space\s+left", re.IGNORECASE),
    re.compile(r"permission\s+denied", re.IGNORECASE),
    re.compile(r"\bENOMEM\b|\bENOSPC\b|\bEACCES\b", re.IGNORECASE),
]

_PATTERN_GROUPS = [
    (FailureType.CRASH, _CRASH_PATTERNS),
    (FailureType.TIMEOUT, _TIMEOUT_PATTERNS),
    (FailureType.CAST_ERROR, _CAST_PATTERNS),
    (FailureType.ASSERTION, _ASSERTION_PATTERNS),
    (FailureType.RESOURCE, _RESOURCE_PATTERNS),
]


def classify_failure(
    message: str,
    module_error: str = "",
) -> FailureType:
    """
    Classify a test failure based on its message and optional module-level error.

    Args:
        message: Test case failure message (from XML ``<failure>`` element).
        module_error: Module-level error from data.js ``"error"`` field
                      (e.g. ``"App died"``).

    Returns:
        A :class:`FailureType` enum value.

    The combined text is matched against pattern groups in priority order:
    CRASH > TIMEOUT > CAST_ERROR > ASSERTION > RESOURCE.
    """
    combined = f"{message} {module_error}".strip()
    if not combined:
        return FailureType.UNKNOWN_FAIL

    for ftype, patterns in _PATTERN_GROUPS:
        for pattern in patterns:
            if pattern.search(combined):
                return ftype

    return FailureType.UNKNOWN_FAIL


def normalize_failure_message(raw: str) -> tuple[str, str]:
    """
    Split a raw failure message into (short_message, detail).

    Strips common prefixes, separates stack traces from the main message,
    and truncates to the first meaningful line.

    Returns:
        ``(short_message, detail_or_stack_trace)``
    """
    if not raw:
        return ("", "")

    lines = raw.strip().split("\n")
    first_line = lines[0].strip()

    for prefix in ("Error: ", "AssertionError: ", "TypeError: ", "ReferenceError: "):
        if first_line.startswith(prefix):
            first_line = first_line[len(prefix):]
            break

    detail = "\n".join(lines[1:]).strip() if len(lines) > 1 else ""
    return (first_line, detail)


def parse_crash_log(text: str) -> CrashInfo:
    """
    Parse a HiviewDFX cppcrash log.

    Extracts the module name, signal, reason, PID, process lifetime,
    and up to five top backtrace frames.
    """
    info = CrashInfo()

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("Module name:"):
            info.module_name = line.split(":", 1)[1].strip()
            continue
        if line.startswith("Pid:"):
            pid_text = line.split(":", 1)[1].strip()
            try:
                info.pid = int(pid_text)
            except ValueError:
                pass
            continue
        if line.startswith("Process life time:"):
            info.process_life_time = line.split(":", 1)[1].strip()
            continue
        if line.startswith("Reason:"):
            info.reason = line.split(":", 1)[1].strip()
            match = re.search(r"Signal:\s*(SIG\w+(?:\([^)]*\))?)", info.reason)
            if match:
                info.signal = match.group(1)
            continue
        if line.startswith("#") and len(info.top_frames) < 5:
            frame = line
            paren_match = re.search(r"\(([^)]+)\)", line)
            if paren_match:
                frame = f"{line.split('(')[0].strip()} -> {paren_match.group(1)}"
            info.top_frames.append(frame)

    return info


# ---------------------------------------------------------------------------
# Root cause clustering
# ---------------------------------------------------------------------------

# Regex replacements for normalizing variable parts of messages.
_NORMALIZE_RULES = [
    # UUID must come before PID/number rules to avoid partial matches.
    (re.compile(
        r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
    ), "UUID"),
    (re.compile(r"0x[0-9a-fA-F]+"), "0xADDR"),
    (re.compile(r"\b\d{4,}\b"), "NUM"),
    (re.compile(r"\s+"), " "),
]


def _normalize_for_clustering(message: str) -> str:
    """
    Normalize a failure message for fingerprinting.

    Strips timestamps, PIDs, hex addresses, UUIDs and collapses whitespace
    so that structurally identical messages with different variable parts
    map to the same fingerprint.
    """
    text = message.lower()
    for pattern, replacement in _NORMALIZE_RULES:
        text = pattern.sub(replacement, text)
    return text.strip()


def _fingerprint(normalized: str) -> str:
    """SHA-256 of a normalized message, truncated to 16 hex characters."""
    return hashlib.sha256(normalized.encode()).hexdigest()[:16]


def cluster_failures(
    transitions: list[TestTransition],
) -> list[RootCauseCluster]:
    """
    Group failed transitions by normalized message fingerprint.

    Only transitions whose ``target_outcome`` is FAIL or ERROR are considered.
    Returns clusters sorted by count (most common first).
    """
    clusters: dict[str, RootCauseCluster] = {}
    _fail_outcomes = {TestOutcome.FAIL, TestOutcome.ERROR}

    for t in transitions:
        if t.target_outcome not in _fail_outcomes:
            continue

        msg = t.target_message or "(no message)"
        ft = t.target_failure_type

        normalized = _normalize_for_clustering(msg)
        fp = _fingerprint(normalized)

        if fp not in clusters:
            clusters[fp] = RootCauseCluster(
                fingerprint=fp,
                failure_type=ft,
                canonical_message=msg,
            )

        cluster = clusters[fp]
        cluster.count += 1
        cluster.test_identities.append(t.identity)
        if t.identity.module not in cluster.modules_affected:
            cluster.modules_affected.append(t.identity.module)
        if len(cluster.example_messages) < 3 and msg not in cluster.example_messages:
            cluster.example_messages.append(msg)
        # Keep shortest non-empty as canonical.
        if msg and msg != "(no message)":
            if (not cluster.canonical_message
                    or cluster.canonical_message == "(no message)"
                    or len(msg) < len(cluster.canonical_message)):
                cluster.canonical_message = msg

    return sorted(clusters.values(), key=lambda c: -c.count)
