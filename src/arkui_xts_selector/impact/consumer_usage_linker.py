"""ConsumerUsageLinker — Universal Impact Resolution Phase C.

Common XTS usage linker for all Phase B resolver domains.
Replaces domain-specific linker helpers: GestureXtsLinker (gesture domain),
_NativePeerXtsLinker (canvas/xcomponent), _NativeEventXtsLinker (native NDK).

Given a list of SdkApiTopics, scans XTS source files for usage of the public
names, classifies usage kind, maps to owning module, and returns
ConsumerUsageEdge records (Phase C normalised model from topic_models.py).

Safety contract (non-negotiable):
- import_only / unknown evidence NEVER has confidence "strong".
- max_bucket is NEVER raised to must_run here or in compute_max_bucket().
- No direct file-to-test hardcode.
- When XTS root is not available: empty edges + xts_index_not_available.
- false_must_run remains 0.

Import boundary: standard library + arkui_xts_selector.impact.topic_models.
"""

from __future__ import annotations

import hashlib
import os
import re
import time
from pathlib import Path
from typing import Optional, Sequence

from arkui_xts_selector.impact.topic_models import (
    ConsumerUsageEdge,
    ImpactTopic,
    SdkApiTopic,
)


# ---------------------------------------------------------------------------
# ConsumerUsageLinker
# ---------------------------------------------------------------------------


class ConsumerUsageLinker:
    """Common XTS usage linker for all Phase B resolver domains.

    Replaces domain-specific linkers: GestureXtsLinker, NativePeer XTS,
    ANI XTS, NativeEvent XTS.

    Given a list of SdkApiTopics, scans XTS source files for usage of the
    public names, classifies usage kind, maps to owning module, and returns
    ConsumerUsageEdge records.

    Degrades gracefully when XTS_ACTS_ROOT is not available.

    Parameters
    ----------
    xts_root:
        Path to the XTS/ACTS root directory.  When ``None`` or not found,
        operates in no-xts mode (empty edges, ``xts_index_not_available``).
    """

    MAX_FILES = 2000
    TIMEOUT_S = 30

    def __init__(self, xts_root: str | Path | None = None) -> None:
        if xts_root is not None:
            self._xts_root: Optional[Path] = Path(xts_root)
        else:
            self._xts_root = self._default_xts_root()
        self._available = (
            self._xts_root is not None and self._xts_root.exists()
        )

    @staticmethod
    def _default_xts_root() -> Optional[Path]:
        r = os.environ.get("XTS_ACTS_ROOT")
        return Path(r) if r else None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def link_sdk_topics(
        self,
        sdk_topics: Sequence[SdkApiTopic],
    ) -> tuple[ConsumerUsageEdge, ...]:
        """Find XTS usage for all public_names in sdk_topics.

        Returns sorted, deduplicated ConsumerUsageEdge tuple.
        Empty when XTS root is not available or sdk_topics is empty.
        """
        if not self._available or not sdk_topics:
            return ()

        assert self._xts_root is not None

        # Map: public_name -> topic_id  (last write wins for duplicates)
        search_names: dict[str, str] = {}
        for topic in sdk_topics:
            for name in topic.public_names:
                search_names[name] = topic.topic_id

        if not search_names:
            return ()

        edges: list[ConsumerUsageEdge] = []
        seen_ids: dict[str, ConsumerUsageEdge] = {}
        deadline = time.monotonic() + self.TIMEOUT_S
        file_count = 0

        for ets_file in self._iter_xts_files():
            if time.monotonic() > deadline or file_count >= self.MAX_FILES:
                break
            file_count += 1

            try:
                content = ets_file.read_text(encoding="utf-8", errors="replace")
            except (OSError, PermissionError):
                continue

            for name, topic_id in search_names.items():
                if name not in content:
                    continue

                for line_num, line in enumerate(content.splitlines(), 1):
                    if name not in line:
                        continue
                    # Skip blank lines and pure comment lines
                    stripped = line.strip()
                    if not stripped or stripped.startswith("//") or stripped.startswith("*"):
                        continue

                    kind = self._classify_usage(name, line)
                    confidence = (
                        "weak" if kind in ("import_only", "unknown") else "strong"
                    )
                    module = self._map_file_to_module(ets_file)

                    edge_id = hashlib.md5(
                        f"{name}:{ets_file}:{line_num}".encode()
                    ).hexdigest()[:12]

                    if edge_id in seen_ids:
                        continue

                    limitations: tuple[str, ...] = ()
                    if kind in ("import_only", "unknown"):
                        limitations = (
                            "import_or_unknown_usage_cannot_raise_bucket",
                        )

                    try:
                        usage_file = str(ets_file.relative_to(self._xts_root))
                    except ValueError:
                        usage_file = str(ets_file)

                    edge = ConsumerUsageEdge(
                        edge_id=edge_id,
                        sdk_api_name=name,
                        sdk_topic_id=topic_id,
                        usage_file=usage_file,
                        usage_line=line_num,
                        usage_kind=kind,
                        usage_symbol=name,
                        owning_module=module,
                        hap_name=None,
                        confidence=confidence,
                        evidence_types=("xts_usage_scan",),
                        limitations=limitations,
                    )
                    seen_ids[edge_id] = edge
                    edges.append(edge)

        return tuple(
            sorted(seen_ids.values(), key=lambda e: (e.sdk_api_name, e.usage_file))
        )

    # ------------------------------------------------------------------
    # File iteration
    # ------------------------------------------------------------------

    def _iter_xts_files(self):
        """Yield .ets and .ts files from XTS root, priority dirs first."""
        assert self._xts_root is not None
        xts_root = self._xts_root

        priority_dir_hints = (
            "arkui",
            "ace_ets_module",
            "ace_ets_component",
            "commonEvents",
            "gesture",
            "canvas",
            "xcomponent",
            "native",
            "ndk",
            "c_arkui",
        )
        seen_files: set[Path] = set()

        # First pass: priority dirs
        for dir_hint in priority_dir_hints:
            for candidate in xts_root.rglob(dir_hint):
                if not candidate.is_dir():
                    continue
                for path in sorted(candidate.rglob("*.ets")):
                    if path not in seen_files:
                        seen_files.add(path)
                        yield path

        # Second pass: all remaining .ets files
        for path in sorted(xts_root.rglob("*.ets")):
            if path not in seen_files:
                seen_files.add(path)
                yield path

    # ------------------------------------------------------------------
    # Usage classification
    # ------------------------------------------------------------------

    @staticmethod
    def _classify_usage(name: str, line: str) -> str:
        """Classify the usage kind of a public API name in a source line."""
        stripped = line.strip()

        # Import line
        if re.match(r"\s*import\b", line):
            return "import_only"

        # Constructor / component instantiation: Name( or Name{ or new Name
        if re.search(rf"(?<![.\w]){re.escape(name)}\s*[\({{]", stripped):
            return "component_instantiation"
        if re.search(rf"\bnew\s+{re.escape(name)}\b", stripped):
            return "component_instantiation"

        # Event handler: .onXxx(
        if re.search(r"\bon[A-Z]\w+\s*\(", stripped):
            return "event_handler"

        # Method call: .name(  or  .anything(
        if re.search(rf"\.{re.escape(name)}\s*\(", stripped):
            return "method_call"
        if re.search(r"\.\w+\s*\(", stripped):
            return "method_call"

        # Property / attribute access
        if re.search(rf"\.\w*{re.escape(name)}\w*", stripped):
            return "property_attribute"

        return "unknown"

    # ------------------------------------------------------------------
    # Module mapping
    # ------------------------------------------------------------------

    @staticmethod
    def _map_file_to_module(path: Path) -> str:
        """Extract owning module key from XTS file path."""
        for part in path.parts:
            if part.startswith(("ace_ets_", "ActsAce", "Acts")):
                return part
        return path.parent.name or "unknown_module"

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def available(self) -> bool:
        """True when the XTS root is available for scanning."""
        return self._available

    def unresolved_reason(self) -> Optional[str]:
        """Return the reason XTS is unavailable, or None when available."""
        if not self._available:
            return "xts_index_not_available"
        return None


# ---------------------------------------------------------------------------
# compute_max_bucket — shared bucket computation rule for all Phase B resolvers
# ---------------------------------------------------------------------------


def compute_max_bucket(
    impact_topics: tuple[ImpactTopic, ...],
    sdk_api_topics: tuple[SdkApiTopic, ...],
    usage_edges: tuple[ConsumerUsageEdge, ...],
) -> str:
    """Common bucket computation rule for all Phase B resolvers.

    Returns: ``"unresolved"`` | ``"possible"`` | ``"recommended"``

    Never returns ``"must_run"`` — that requires exact coverage equivalence
    plus a runnable target (handled separately by the gate, not by resolvers).

    Rules
    -----
    - No impact topics → ``"unresolved"``
    - No SDK topics → ``"possible"``
    - SDK topics but no usage edges → ``"possible"``
    - Only ``import_only`` or ``unknown`` edges → ``"possible"``
    - SDK topics + non-import strong usage → ``"recommended"``
    """
    if not impact_topics:
        return "unresolved"

    if not sdk_api_topics:
        return "possible"

    if not usage_edges:
        return "possible"

    strong_edges = [
        e for e in usage_edges
        if e.usage_kind not in ("import_only", "unknown")
    ]
    if not strong_edges:
        return "possible"

    # SDK declaration + non-import usage → recommended
    # Safety gate: never must_run
    result = "recommended"
    assert result != "must_run", "compute_max_bucket: must_run is forbidden"
    return result
