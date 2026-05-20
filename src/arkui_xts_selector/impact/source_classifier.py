"""Source path classifier for Universal Impact Resolution — Phase A.

Classifies ArkUI AceEngine source paths into ``SourceImpactEntity`` records
using ordered rules from ``config/source_layers.json``.

This module is additive and does not affect production selector scoring,
bucket assignment, or must_run logic.

Import boundary: this module imports only the standard library and
``arkui_xts_selector.impact.models``.
"""

from __future__ import annotations

import json
import os
import pathlib
import re
from typing import Any

from arkui_xts_selector.impact.models import (
    ConfidenceLevel,
    EvidenceRef,
    SourceImpactEntity,
    SourceLayer,
    SourceRole,
)


# ---------------------------------------------------------------------------
# Suffixes stripped when deriving owner_family_hint from filename
# ---------------------------------------------------------------------------

_FAMILY_STRIP_SUFFIXES = (
    "_peer_impl",
    "_accessor",
    "_modifier",
    "_recognizer",
    "_referee",
    "_impl",
    "_ani",
    "_binding",
    "_bridge",
    "_node",
    "_event",
    "_extender",
    "_helper",
    "_ops",
    "_register",
    "_register_impl",
    "_extender_accessor",
    "_common_method",
)

# Layer-specific limitation sets
_LAYER_LIMITATIONS: dict[str, tuple[str, ...]] = {
    "native_peer": (
        "owner_family_hint_is_lookup_evidence_only",
        "sdk_declaration_not_verified",
    ),
    "jsi_bridge": (
        "no_direct_sdk_api_resolved",
        "broad_profile_only",
    ),
    "gesture_framework": (
        "gesture_api_topics_not_resolved_to_sdk",
    ),
    "gesture_referee": (
        "gesture_api_topics_not_resolved_to_sdk",
        "shared_gesture_infrastructure",
    ),
    "unknown": (
        "no_rule_matched",
        "manual_review_required",
    ),
    "ani_bridge": (
        "ani_symbol_is_bridge_evidence_only",
        "sdk_declaration_not_verified",
    ),
    "native_event": (
        "prefer_native_xts_consumers_over_broad_arkets_fanout",
    ),
    "native_node": (
        "prefer_native_xts_consumers_over_broad_arkets_fanout",
    ),
}


def _strip_family_suffixes(stem: str) -> str:
    """Strip known implementation suffixes from a filename stem."""
    name = stem.lower()
    changed = True
    while changed:
        changed = False
        for suffix in _FAMILY_STRIP_SUFFIXES:
            if name.endswith(suffix):
                name = name[: -len(suffix)]
                changed = True
                break
    return name


def _extract_family_hint(path: str) -> str | None:
    """Derive component family hint from filename stem."""
    stem = pathlib.Path(path).stem
    if not stem:
        return None
    stripped = _strip_family_suffixes(stem)
    return stripped if stripped else None


class SourceClassifier:
    """Classify ArkUI source paths into ``SourceImpactEntity`` records.

    Rules are loaded once from ``config/source_layers.json`` (relative to
    the package root) or from the optional ``rules_path`` argument.  Rules
    are evaluated in declaration order; the first match wins.

    Parameters
    ----------
    rules_path:
        Explicit path to a ``source_layers.json`` file.  When ``None``,
        the default config shipped with the package is used.
    """

    def __init__(self, rules_path: str | None = None) -> None:
        if rules_path is None:
            # Resolve relative to the package root (two levels up from this file)
            pkg_root = pathlib.Path(__file__).parent.parent.parent.parent
            rules_path = str(pkg_root / "config" / "source_layers.json")
        self._rules_path = rules_path
        self._rules: list[dict[str, Any]] = []
        self._compiled: list[tuple[re.Pattern[str], dict[str, Any]]] = []
        self._load_rules()

    # ------------------------------------------------------------------
    # Rule loading
    # ------------------------------------------------------------------

    def _load_rules(self) -> None:
        with open(self._rules_path, encoding="utf-8") as fh:
            data = json.load(fh)
        self._rules = data.get("rules", [])
        self._compiled = [
            (re.compile(rule["path_regex"]), rule)
            for rule in self._rules
        ]

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def classify_path(
        self,
        path: str,
        changed_symbols: tuple[str, ...] = (),
        changed_hunks: tuple[str, ...] = (),
    ) -> SourceImpactEntity:
        """Classify a single source path.

        Parameters
        ----------
        path:
            Repository-relative path (absolute paths are accepted; the
            common ace_engine prefix is stripped internally for matching).
        changed_symbols:
            Optional tuple of symbol names extracted from the diff.
        changed_hunks:
            Optional tuple of hunk description strings.

        Returns
        -------
        SourceImpactEntity
            A fully populated entity.  If no rule matches, ``layer="unknown"``
            and ``confidence="none"``.
        """
        # Normalise: strip leading absolute prefix up to ace_engine/
        normalised = _normalise_path(path)

        matched_rule: dict[str, Any] | None = None
        for pattern, rule in self._compiled:
            if pattern.search(normalised):
                matched_rule = rule
                break

        if matched_rule is None:
            return self._make_unknown(path, changed_symbols, changed_hunks)

        return self._build_entity(
            path=path,
            normalised=normalised,
            rule=matched_rule,
            changed_symbols=changed_symbols,
            changed_hunks=changed_hunks,
        )

    def classify_paths(
        self,
        paths: list[str],
    ) -> list[SourceImpactEntity]:
        """Classify a list of source paths.

        Returns one entity per path, in the same order as ``paths``.
        """
        return [self.classify_path(p) for p in paths]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_entity(
        self,
        path: str,
        normalised: str,
        rule: dict[str, Any],
        changed_symbols: tuple[str, ...],
        changed_hunks: tuple[str, ...],
    ) -> SourceImpactEntity:
        layer: SourceLayer = rule["layer"]
        role: SourceRole = rule["role"]
        confidence: ConfidenceLevel = rule.get("confidence", "none")
        rule_id: str = rule["id"]
        family_from_filename: bool = rule.get("family_from_filename", False)

        # Derive owner_family_hint
        owner_family_hint: str | None = None
        if family_from_filename:
            owner_family_hint = _extract_family_hint(normalised)

        # Expand topic templates
        source_topic_hints = _expand_topic_templates(
            rule.get("topic_templates", []),
            family=owner_family_hint,
        )

        # Build evidence refs
        evidence: list[EvidenceRef] = [EvidenceRef(kind="path_match", value=rule_id)]
        for sym in changed_symbols:
            evidence.append(EvidenceRef(kind="symbol", value=sym))

        # Layer-specific limitations
        limitations: tuple[str, ...] = _LAYER_LIMITATIONS.get(layer, ())

        entity_id = f"{path}#{layer}#{role}"

        return SourceImpactEntity(
            id=entity_id,
            path=path,
            changed_symbols=changed_symbols,
            changed_hunks=changed_hunks,
            layer=layer,
            role=role,
            owner_family_hint=owner_family_hint,
            source_topic_hints=tuple(source_topic_hints),
            confidence=confidence,
            evidence=tuple(evidence),
            limitations=limitations,
        )

    def _make_unknown(
        self,
        path: str,
        changed_symbols: tuple[str, ...],
        changed_hunks: tuple[str, ...],
    ) -> SourceImpactEntity:
        evidence: list[EvidenceRef] = [EvidenceRef(kind="path_match", value="unknown")]
        for sym in changed_symbols:
            evidence.append(EvidenceRef(kind="symbol", value=sym))

        return SourceImpactEntity(
            id=f"{path}#unknown#unknown",
            path=path,
            changed_symbols=changed_symbols,
            changed_hunks=changed_hunks,
            layer="unknown",
            role="unknown",
            owner_family_hint=None,
            source_topic_hints=(),
            confidence="none",
            evidence=tuple(evidence),
            limitations=_LAYER_LIMITATIONS["unknown"],
        )


# ---------------------------------------------------------------------------
# Path normalisation
# ---------------------------------------------------------------------------

_ACE_ENGINE_PREFIX = "foundation/arkui/ace_engine/"
_ACE_ENGINE_FRAMEWORKS_PREFIX = "foundation/arkui/ace_engine/frameworks/"


def _normalise_path(path: str) -> str:
    """Return a path relative to the ace_engine root for rule matching.

    Strips any absolute filesystem prefix up to and including
    ``foundation/arkui/ace_engine/``.  If the path does not contain that
    prefix the path is returned as-is (already normalised).
    """
    # Handle absolute paths: find the ace_engine marker
    for marker in ("foundation/arkui/ace_engine/frameworks/",
                   "foundation/arkui/ace_engine/"):
        idx = path.find(marker)
        if idx != -1:
            return path[idx + len(marker):]
    # Return as-is (already relative or unknown structure)
    return path


# ---------------------------------------------------------------------------
# Topic template expansion
# ---------------------------------------------------------------------------

def _expand_topic_templates(
    templates: list[str],
    family: str | None,
) -> list[str]:
    """Expand ``{family}`` placeholders in topic templates.

    If a template contains ``{family}`` but no family hint is available,
    the template is included verbatim with ``{family}`` replaced by
    ``unknown``.
    """
    result: list[str] = []
    for tmpl in templates:
        if "{family}" in tmpl:
            resolved = family if family else "unknown"
            result.append(tmpl.replace("{family}", resolved))
        else:
            result.append(tmpl)
    return result
