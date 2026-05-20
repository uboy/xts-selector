"""GestureSdkValidator — Universal Impact Resolution Phase B.2.

Validates gesture ImpactTopics against SDK declarations found in the
``interface_sdk-js/api`` directory tree.

Scope: gesture domain only (PanGesture, TapGesture, etc.).
       No C-API, no JSI, no CommonMethod, no NativeEvent expansion.

Safety contract (non-negotiable):
- Internal C++ names never appear as public SDK API names.
- max_bucket is NEVER raised to must_run by this validator.
- When SDK root is not available: graceful degradation, sdk_index_not_available.
- When a name is queried but not found: sdk_declaration_missing:<name>.

Import boundary: standard library + arkui_xts_selector.impact.*.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Optional

from arkui_xts_selector.impact.topic_models import (
    ApiDeclarationRef,
    ImpactTopic,
    SdkApiTopic,
)

# ---------------------------------------------------------------------------
# Regex: detect a public declaration in a .d.ts / .d.ets file.
# We look for patterns like:
#   declare class PanGesture { ... }
#   export declare interface PanGestureOptions { ... }
#   declare function PanGesture(...): ...
#   export declare enum GestureDirection { ... }
#   declare const onGestureRecognizerJudgeBegin: ...
#   export interface PanGesture { ... }
# The key requirement: ``export`` and/or ``declare`` keyword before the identifier.
# ---------------------------------------------------------------------------
_RE_DECL = re.compile(
    r"(?:export\s+)?declare\s+(?:class|interface|function|enum|const|type|namespace)\s+"
    r"(?P<name>[A-Za-z_][A-Za-z0-9_]*)",
)
# Also match plain export interface / export class / export function patterns
# (some .d.ets files omit "declare" but use "export")
_RE_EXPORT = re.compile(
    r"\bexport\s+(?:(?:default|abstract|readonly)\s+)*"
    r"(?:class|interface|function|enum|const|type|namespace|struct)\s+"
    r"(?P<name>[A-Za-z_][A-Za-z0-9_]*)",
)

# Gesture-relevant candidate filenames to search first (speeds up lookup)
_GESTURE_SDK_FILENAME_HINTS = (
    "gesture",
    "panGesture",
    "tapGesture",
    "longPressGesture",
    "swipeGesture",
    "pinchGesture",
    "rotationGesture",
    "gestureEvent",
    "gestureRecognizer",
    "gestureGroup",
)


def _extract_declared_names(sdk_file: Path) -> frozenset[str]:
    """Return all public-declared names found in a .d.ts / .d.ets file."""
    try:
        text = sdk_file.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return frozenset()
    names: set[str] = set()
    for m in _RE_DECL.finditer(text):
        names.add(m.group("name"))
    for m in _RE_EXPORT.finditer(text):
        names.add(m.group("name"))
    return frozenset(names)


def _build_sdk_name_index(sdk_api_root: Path) -> dict[str, str]:
    """Build a mapping of public_name -> sdk_file_path for gesture-relevant names.

    Strategy (in priority order):
    1. Scan files whose names contain gesture-relevant hints.
    2. Scan ``@ohos.arkui.*.d.ets`` files.
    3. Scan ``@internal/component/ets/*.d.ts`` files.
    4. Fall back to scanning all ``.d.ts`` / ``.d.ets`` files (bounded by count).

    Returns empty dict when the root does not exist.
    """
    if not sdk_api_root.exists():
        return {}

    name_to_path: dict[str, str] = {}
    scanned: set[Path] = set()

    def scan(file: Path) -> None:
        if file in scanned:
            return
        scanned.add(file)
        for name in _extract_declared_names(file):
            if name not in name_to_path:
                name_to_path[name] = str(file)

    # Priority 1: gesture-hinted filenames
    for hint in _GESTURE_SDK_FILENAME_HINTS:
        for f in sdk_api_root.rglob(f"*{hint}*.d.ts"):
            scan(f)
        for f in sdk_api_root.rglob(f"*{hint}*.d.ets"):
            scan(f)

    # Priority 2: @ohos.arkui.*.d.ets
    for f in sdk_api_root.rglob("@ohos.arkui.*.d.ets"):
        scan(f)

    # Priority 3: @internal/component/ets/*.d.ts
    ets_dir = sdk_api_root / "@internal" / "component" / "ets"
    if ets_dir.exists():
        for f in sorted(ets_dir.glob("*.d.ts"))[:200]:
            scan(f)

    # Priority 4: broad scan (bounded to avoid timeouts)
    if len(scanned) < 50:
        count = 0
        for f in sdk_api_root.rglob("*.d.ts"):
            if f not in scanned:
                scan(f)
                count += 1
                if count >= 500:
                    break
        count = 0
        for f in sdk_api_root.rglob("*.d.ets"):
            if f not in scanned:
                scan(f)
                count += 1
                if count >= 500:
                    break

    return name_to_path


class GestureSdkValidator:
    """Validates gesture ImpactTopics against SDK declarations.

    Produces ``SdkApiTopic`` records for gesture-domain topics.

    Parameters
    ----------
    sdk_api_root:
        Path to the ``interface_sdk-js/api`` directory.
        If ``None`` or not found: operates in no-sdk mode (graceful degradation).
    """

    def __init__(self, sdk_api_root: Optional[str] = None) -> None:
        root_str = sdk_api_root or os.environ.get("INTERFACE_SDK_JS_ROOT")
        self._sdk_root: Optional[Path] = Path(root_str) if root_str else None
        self._name_index: Optional[dict[str, str]] = None  # lazy init
        self._available: Optional[bool] = None  # lazy init

    # ------------------------------------------------------------------
    # Internal: lazy index
    # ------------------------------------------------------------------

    def _ensure_index(self) -> None:
        """Build the SDK name index (once, lazily)."""
        if self._available is not None:
            return
        if self._sdk_root is None or not self._sdk_root.exists():
            self._available = False
            self._name_index = {}
            return
        self._name_index = _build_sdk_name_index(self._sdk_root)
        self._available = True

    @property
    def is_available(self) -> bool:
        self._ensure_index()
        return bool(self._available)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def validate_topic(self, topic: ImpactTopic) -> SdkApiTopic:
        """Validate an ImpactTopic against SDK declarations.

        Parameters
        ----------
        topic:
            An ``ImpactTopic`` produced by Phase B.1 routing.

        Returns
        -------
        SdkApiTopic:
            - declarations found → ``api_confidence = "strong"`` or ``"medium"``
            - declarations missing → ``api_confidence = "none"``,
              ``unresolved_reason = "sdk_declaration_missing:<Name>"``
            - no SDK root → ``api_confidence = "none"`` (inherited),
              ``limitation = "sdk_index_not_available"``
        """
        self._ensure_index()

        if not self.is_available:
            # Graceful degradation: preserve the topic but mark as not validated
            return SdkApiTopic(
                topic_id=topic.topic_id,
                public_names=(),
                declarations=(),
                expected_usage_kinds=topic.expected_sdk_kinds,
                source_topic_ids=(topic.topic_id,),
                api_confidence="none",
                unresolved_reasons=("sdk_index_not_available",),
            )

        assert self._name_index is not None  # guaranteed by is_available path
        name_index = self._name_index

        # Gather the sdk_api_queries from topic's expected_sdk_kinds.
        # ImpactTopic.expected_sdk_kinds comes from api_topics.json sdk_api_queries[].kind
        # — we need the public_names, which are stored in the topic.
        # However, ImpactTopic doesn't carry public_names directly.
        # We infer them from the api_topics config via topic_id → sdk_api_queries.
        # Since we don't have config here, we use the workaround of scanning
        # expected_sdk_kinds to find what names to look for.
        #
        # DESIGN NOTE: ImpactTopic only carries expected_sdk_kinds (the "kind" strings
        # like "component", "configuration"), not the actual public_names.
        # We resolve names from the existing SdkApiTopic in the resolver output.
        # This validator is called with pre-built SdkApiTopics from Phase B.1 and
        # re-validates their public_names against the real SDK index.
        # When called via validate_topic(ImpactTopic), we return a minimal record.
        # The real validation path goes through validate_sdk_topic().
        return SdkApiTopic(
            topic_id=topic.topic_id,
            public_names=(),
            declarations=(),
            expected_usage_kinds=topic.expected_sdk_kinds,
            source_topic_ids=(topic.topic_id,),
            api_confidence="none",
            unresolved_reasons=("no_public_names_in_impact_topic",),
        )

    def validate_sdk_topic(self, sdk_topic: SdkApiTopic) -> SdkApiTopic:
        """Re-validate an existing SdkApiTopic against the real SDK index.

        This is the primary validation path.  Takes an existing ``SdkApiTopic``
        produced by Phase B.1 (which may have ``sdk_not_validated`` in its
        unresolved_reasons) and looks up each ``public_name`` against the real
        SDK index.

        Parameters
        ----------
        sdk_topic:
            An ``SdkApiTopic`` from Phase B.1 resolution.

        Returns
        -------
        SdkApiTopic:
            Updated topic with validated declarations.
        """
        self._ensure_index()

        if not self.is_available:
            # Preserve existing topic content, just add the sdk_not_available reason
            existing_reasons = set(sdk_topic.unresolved_reasons)
            new_reasons = (
                tuple(sdk_topic.unresolved_reasons)
                if "sdk_index_not_available" in existing_reasons
                else sdk_topic.unresolved_reasons + ("sdk_index_not_available",)
            )
            return SdkApiTopic(
                topic_id=sdk_topic.topic_id,
                public_names=sdk_topic.public_names,
                declarations=sdk_topic.declarations,
                expected_usage_kinds=sdk_topic.expected_usage_kinds,
                source_topic_ids=sdk_topic.source_topic_ids,
                api_confidence=sdk_topic.api_confidence,
                unresolved_reasons=new_reasons,
            )

        assert self._name_index is not None
        name_index = self._name_index

        validated_names: list[str] = []
        validated_decls: list[ApiDeclarationRef] = []
        unresolved: list[str] = []

        for public_name in sdk_topic.public_names:
            if public_name in name_index:
                sdk_path = name_index[public_name]
                # Find matching declaration from existing declarations (if any)
                existing_decl = next(
                    (d for d in sdk_topic.declarations if d.public_name == public_name),
                    None,
                )
                if existing_decl is not None:
                    # Use existing decl, update sdk_path_hint from real file
                    validated_decls.append(
                        ApiDeclarationRef(
                            public_name=public_name,
                            kind=existing_decl.kind,
                            sdk_path_hint=sdk_path,
                        )
                    )
                else:
                    validated_decls.append(
                        ApiDeclarationRef(
                            public_name=public_name,
                            kind="component",  # default for gesture
                            sdk_path_hint=sdk_path,
                        )
                    )
                validated_names.append(public_name)
            else:
                unresolved.append(f"sdk_declaration_missing:{public_name}")

        # Determine api_confidence
        if validated_names and not unresolved:
            api_confidence = "strong"
        elif validated_names:
            api_confidence = "medium"
        else:
            api_confidence = "none"

        # Deduplicate unresolved
        seen: set[str] = set()
        deduped: list[str] = []
        for r in unresolved:
            if r not in seen:
                seen.add(r)
                deduped.append(r)

        return SdkApiTopic(
            topic_id=sdk_topic.topic_id,
            public_names=tuple(validated_names),
            declarations=tuple(validated_decls),
            expected_usage_kinds=sdk_topic.expected_usage_kinds,
            source_topic_ids=sdk_topic.source_topic_ids,
            api_confidence=api_confidence,
            unresolved_reasons=tuple(deduped),
        )

    def validate_topics(self, topics: list[ImpactTopic]) -> list[SdkApiTopic]:
        """Validate a list of ImpactTopics (returns minimal records).

        For full validation pass pre-built SdkApiTopics through
        ``validate_sdk_topics()`` instead.
        """
        return [self.validate_topic(t) for t in topics]

    def validate_sdk_topics(self, sdk_topics: list[SdkApiTopic]) -> list[SdkApiTopic]:
        """Validate a list of pre-built SdkApiTopics against the real SDK index."""
        return [self.validate_sdk_topic(t) for t in sdk_topics]
