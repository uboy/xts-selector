"""GestureXtsLinker — Universal Impact Resolution Phase B.2.

Links SdkApiTopics to XTS consumer usage via filesystem scan of .ets files
in the XTS/ACTS arkui directory.  Produces ``ConsumerUsageEdge`` records.

Scope: gesture domain only.
       Searches gesture-relevant subdirectories to avoid timeouts.

Safety contract (non-negotiable):
- import_only evidence NEVER has confidence "strong".
- max_bucket is NEVER raised to must_run here.
- No direct file-to-test hardcode.
- When XTS root is not available: empty edges + xts_index_not_available.
- false_must_run remains 0.

Import boundary: standard library + arkui_xts_selector.impact.*.
"""

from __future__ import annotations

import hashlib
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from arkui_xts_selector.impact.topic_models import SdkApiTopic

# ---------------------------------------------------------------------------
# ConsumerUsageEdge — result model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ConsumerUsageEdge:
    """An XTS consumer usage edge linking an SDK API topic to a test file.

    Fields
    ------
    edge_id
        Stable hash-based identifier: ``"{sdk_api_topic_id}#{consumer_file}#{api_public_name}"``.
    sdk_api_topic_id
        The ``SdkApiTopic.topic_id`` this edge is linked to.
    api_public_name
        The SDK-visible public name that was found in the XTS file.
    consumer_file
        Relative path to the XTS consumer file (relative to XTS root).
    consumer_project
        Project/module key derived from the file path.
    usage_kind
        ``"component_instantiation"``, ``"event_handler"``, ``"method_call"``,
        or ``"import_only"``.
        ``import_only`` cannot reach ``must_run``.
    confidence
        ``"strong"``, ``"medium"``, or ``"weak"``.
        ``import_only`` → ``"weak"`` always.
    evidence
        A snippet of the matched line (truncated to 120 chars).
    limitations
        Tuple of limitation strings (empty for strong evidence).
    """

    edge_id: str
    sdk_api_topic_id: str
    api_public_name: str
    consumer_file: str
    consumer_project: str
    usage_kind: str
    confidence: str
    evidence: str
    limitations: tuple[str, ...]


# ---------------------------------------------------------------------------
# Regex patterns for gesture usage detection
# ---------------------------------------------------------------------------

# Import: import { PanGesture } from '@ohos.multimodalInput.gestureEvent'
_RE_IMPORT = re.compile(
    r"\bimport\b.*?\b(?P<name>[A-Z][A-Za-z0-9]+)\b.*\bfrom\b"
)

# Component instantiation: PanGesture({...}) or new PanGesture(
# Also covers: .PanGesture({...}) or PanGesture()
_RE_INSTANTIATION = re.compile(
    r"(?<![.\w])(?P<name>[A-Z][A-Za-z0-9]+)\s*\("
)

# Event handler: .onGestureRecognizerJudgeBegin(...)  or .onGestureJudgeBegin(...)
_RE_EVENT_HANDLER = re.compile(
    r"\.\s*(?P<name>on[A-Z][A-Za-z0-9]+)\s*\("
)

# Method call: .addGesture(...) .setGestureJudgeBeginCallback(...) etc.
_RE_METHOD_CALL = re.compile(
    r"\.\s*(?P<name>[a-z][A-Za-z0-9]+)\s*\("
)

# Gesture-related subdirectory hints (order matters — more specific first)
_XTS_GESTURE_DIR_HINTS = (
    "gestureRecognition",
    "gesture",
    "commonEvents",
    "panGesture",
    "tapGesture",
    "longPressGesture",
    "swipeGesture",
    "pinchGesture",
    "rotationGesture",
    "gestureGroup",
    "customGestureRecognition",
    "gestureHandler",
    "gestureEvent",
)

# Max files to scan per public_name to avoid timeouts
_MAX_FILES = 2000
# Max time in seconds for the full scan
_MAX_SCAN_SECONDS = 30


def _make_edge_id(topic_id: str, consumer_file: str, public_name: str) -> str:
    raw = f"{topic_id}#{consumer_file}#{public_name}"
    return hashlib.sha1(raw.encode()).hexdigest()[:16]


def _truncate_evidence(text: str, max_len: int = 120) -> str:
    text = text.strip()
    return text[:max_len] + "…" if len(text) > max_len else text


def _derive_project(consumer_file: str) -> str:
    """Derive a project/module key from the consumer file path.

    The project key is the first meaningful directory part of the relative path
    (i.e. the test module directory name).
    """
    parts = Path(consumer_file).parts
    if len(parts) >= 2:
        return parts[0]
    return consumer_file


def _collect_gesture_dirs(xts_root: Path) -> list[Path]:
    """Collect gesture-relevant directories within the XTS root."""
    collected: list[Path] = []
    seen: set[Path] = set()

    def add(p: Path) -> None:
        if p.exists() and p not in seen:
            seen.add(p)
            collected.append(p)

    for hint in _XTS_GESTURE_DIR_HINTS:
        for d in xts_root.rglob(hint):
            if d.is_dir():
                add(d)

    # Fallback: include root itself so broad scan works if specific dirs absent
    if not collected:
        add(xts_root)

    return collected


def _scan_file_for_names(
    file_path: Path,
    xts_root: Path,
    public_names: frozenset[str],
) -> list[tuple[str, str, str, str]]:
    """Scan a single .ets file for gesture name occurrences.

    Returns list of (public_name, usage_kind, confidence, evidence_snippet).
    """
    try:
        text = file_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []

    try:
        rel_path = str(file_path.relative_to(xts_root))
    except ValueError:
        rel_path = str(file_path)

    results: list[tuple[str, str, str, str]] = []
    lines = text.splitlines()

    for _lineno, raw_line in enumerate(lines, start=1):
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("//") or stripped.startswith("*"):
            continue

        # Check import
        for m in _RE_IMPORT.finditer(raw_line):
            name = m.group("name")
            if name in public_names:
                results.append((name, "import_only", "weak",
                                 _truncate_evidence(raw_line)))

        # Check instantiation (PanGesture({...}), TapGesture(), etc.)
        for m in _RE_INSTANTIATION.finditer(raw_line):
            name = m.group("name")
            if name in public_names:
                # Not an import, more meaningful
                results.append((name, "component_instantiation", "strong",
                                 _truncate_evidence(raw_line)))

        # Check event handlers (.onGestureRecognizerJudgeBegin, .onGestureJudgeBegin)
        for m in _RE_EVENT_HANDLER.finditer(raw_line):
            name = m.group("name")
            if name in public_names:
                results.append((name, "event_handler", "strong",
                                 _truncate_evidence(raw_line)))

    return results


class GestureXtsLinker:
    """Links SdkApiTopics to XTS usage via consumer project index.

    Produces ``ConsumerUsageEdge`` records by scanning XTS source files
    for occurrences of gesture SDK public names.

    Parameters
    ----------
    xts_root:
        Path to the XTS/ACTS arkui directory (or its parent).
        If ``None`` or not found: operates in no-xts mode (empty edges).
    """

    def __init__(self, xts_root: Optional[str] = None) -> None:
        root_str = xts_root or os.environ.get("XTS_ACTS_ROOT")
        self._xts_root: Optional[Path] = Path(root_str) if root_str else None
        self._available: Optional[bool] = None  # lazy init

    def _ensure_available(self) -> None:
        if self._available is not None:
            return
        self._available = (
            self._xts_root is not None and self._xts_root.exists()
        )

    @property
    def is_available(self) -> bool:
        self._ensure_available()
        return bool(self._available)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def find_usage_edges(self, sdk_topic: SdkApiTopic) -> list[ConsumerUsageEdge]:
        """Search XTS source files for usage of public_names from sdk_topic.

        Returns edges with consumer_file, consumer_project, usage_kind.

        Parameters
        ----------
        sdk_topic:
            An ``SdkApiTopic`` with public_names to search for.

        Returns
        -------
        list[ConsumerUsageEdge]:
            Edges found.  Empty when XTS root is not available or no names
            were found.  Contains only gesture-domain results.
        """
        self._ensure_available()
        if not self.is_available or not sdk_topic.public_names:
            return []

        assert self._xts_root is not None
        xts_root = self._xts_root

        public_names = frozenset(sdk_topic.public_names)
        gesture_dirs = _collect_gesture_dirs(xts_root)
        edges: list[ConsumerUsageEdge] = []
        seen_edges: set[str] = set()
        file_count = 0
        start_time = time.monotonic()

        for gesture_dir in gesture_dirs:
            for ets_file in sorted(gesture_dir.rglob("*.ets")):
                if file_count >= _MAX_FILES:
                    break
                if time.monotonic() - start_time > _MAX_SCAN_SECONDS:
                    break

                file_count += 1
                hits = _scan_file_for_names(ets_file, xts_root, public_names)
                if not hits:
                    continue

                try:
                    rel_path = str(ets_file.relative_to(xts_root))
                except ValueError:
                    rel_path = str(ets_file)

                consumer_project = _derive_project(rel_path)

                for public_name, usage_kind, confidence, evidence in hits:
                    # import_only cannot be "strong"
                    assert not (usage_kind == "import_only" and confidence == "strong"), \
                        "import_only confidence must not be strong"

                    limitations: tuple[str, ...] = ()
                    if usage_kind == "import_only":
                        limitations = ("import_only_cannot_reach_must_run",)

                    edge_id = _make_edge_id(sdk_topic.topic_id, rel_path, public_name)
                    if edge_id in seen_edges:
                        continue
                    seen_edges.add(edge_id)

                    edges.append(ConsumerUsageEdge(
                        edge_id=edge_id,
                        sdk_api_topic_id=sdk_topic.topic_id,
                        api_public_name=public_name,
                        consumer_file=rel_path,
                        consumer_project=consumer_project,
                        usage_kind=usage_kind,
                        confidence=confidence,
                        evidence=evidence,
                        limitations=limitations,
                    ))

            if file_count >= _MAX_FILES or time.monotonic() - start_time > _MAX_SCAN_SECONDS:
                break

        return edges

    def find_usage_edges_for_topics(
        self, sdk_topics: list[SdkApiTopic]
    ) -> list[ConsumerUsageEdge]:
        """Find usage edges for a list of SdkApiTopics."""
        all_edges: list[ConsumerUsageEdge] = []
        for topic in sdk_topics:
            all_edges.extend(self.find_usage_edges(topic))
        return all_edges

    def _map_file_to_project(self, consumer_file: str) -> str:
        """Map XTS file path to project/module key."""
        return _derive_project(consumer_file)
