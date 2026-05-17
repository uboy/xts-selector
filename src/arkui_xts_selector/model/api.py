"""Canonical API identity and declaration types.

This module defines stable, deterministic identifiers for OpenHarmony SDK APIs
and their declarations.  It is a pure data module with no filesystem or network
side-effects.

Import boundary: this module imports only the standard library.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Literal


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class ApiEntityKind(enum.Enum):
    """Kind of an API entity within the SDK surface."""

    COMPONENT = "component"
    MODIFIER = "modifier"
    ATTRIBUTE = "attribute"
    EVENT_OR_METHOD = "event_or_method"
    MODULE = "module"
    CONFIGURATION = "configuration"
    HELPER_FAMILY = "helper_family"


class ApiSurfaceKind(enum.Enum):
    """Binding surface of an API entity."""

    STATIC = "static"
    DYNAMIC = "dynamic"
    SHARED = "shared"
    UNKNOWN = "unknown"


# ---------------------------------------------------------------------------
# Helpers – deterministic percent-encoding
# ---------------------------------------------------------------------------

_RESERVED_MAP = str.maketrans(
    {
        "#": "%23",
        ":": "%3A",
        "/": "%2F",
        ".": "%2E",
        " ": "%20",
    }
)


def _encode(value: str) -> str:
    """Percent-encode reserved characters in a canonical-id value segment."""
    return value.translate(_RESERVED_MAP)


# ---------------------------------------------------------------------------
# ApiEntityId – the stable identity of a public SDK API
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ApiEntityId:
    """Stable, deterministic identifier for a public SDK API entity.

    Canonical string format::

        api:<schema_version>:<namespace>.<surface>:<kind>:<module>#<public_name>

    Public API ids always start with ``api:``.  Internal, generated, or helper
    entities must use a different prefix (``internal:`` or ``helper:``).
    """

    schema_version: Literal["v1"] = "v1"
    namespace: str = ""
    surface: str = "unknown"  # ApiSurfaceKind value
    kind: str = ""  # ApiEntityKind value
    module: str = ""
    public_name: str = ""
    member_of: str | None = None
    member_name: str | None = None

    # -- construction helpers ------------------------------------------------

    @classmethod
    def from_parts(
        cls,
        *,
        namespace: str = "",
        surface: str = "unknown",
        kind: str = "",
        module: str = "",
        public_name: str = "",
        member_of: str | None = None,
        member_name: str | None = None,
    ) -> ApiEntityId:
        """Create an ``ApiEntityId`` with explicit keyword fields."""
        return cls(
            namespace=namespace,
            surface=surface,
            kind=kind,
            module=module,
            public_name=public_name,
            member_of=member_of,
            member_name=member_name,
        )

    # -- canonical string ----------------------------------------------------

    def canonical(self) -> str:
        """Return the deterministic canonical string for this identity.

        Format: ``api:v1:<namespace>.<surface>:<kind>:<module>#<name>``

        When ``member_of`` and ``member_name`` are set the name segment
        becomes ``<member_of>#<member_name>`` to distinguish nested members.
        """
        surface_val = self.surface
        ns_surface = f"{_encode(self.namespace)}.{_encode(surface_val)}"
        kind_enc = _encode(self.kind)
        module_enc = _encode(self.module)

        if self.member_of and self.member_name:
            name_enc = f"{_encode(self.member_of)}%23{_encode(self.member_name)}"
        else:
            name_enc = _encode(self.public_name)

        return (
            f"api:{self.schema_version}:{ns_surface}:{kind_enc}:{module_enc}#{name_enc}"
        )

    # -- serialization -------------------------------------------------------

    def to_dict(self) -> dict:
        """Return a JSON-compatible dict with deterministic key order."""
        d: dict[str, object] = {
            "schema_version": self.schema_version,
            "namespace": self.namespace,
            "surface": self.surface,
            "kind": self.kind,
            "module": self.module,
            "public_name": self.public_name,
        }
        if self.member_of is not None:
            d["member_of"] = self.member_of
        if self.member_name is not None:
            d["member_name"] = self.member_name
        return d

    @classmethod
    def from_dict(cls, data: dict) -> ApiEntityId:
        """Reconstruct from a dict produced by :meth:`to_dict`."""
        return cls(
            schema_version=data.get("schema_version", "v1"),
            namespace=data.get("namespace", ""),
            surface=data.get("surface", "unknown"),
            kind=data.get("kind", ""),
            module=data.get("module", ""),
            public_name=data.get("public_name", ""),
            member_of=data.get("member_of"),
            member_name=data.get("member_name"),
        )

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, ApiEntityId):
            return NotImplemented
        return self.canonical() < other.canonical()

    def __le__(self, other: object) -> bool:
        if not isinstance(other, ApiEntityId):
            return NotImplemented
        return self.canonical() <= other.canonical()

    def __gt__(self, other: object) -> bool:
        if not isinstance(other, ApiEntityId):
            return NotImplemented
        return self.canonical() > other.canonical()

    def __ge__(self, other: object) -> bool:
        if not isinstance(other, ApiEntityId):
            return NotImplemented
        return self.canonical() >= other.canonical()


# ---------------------------------------------------------------------------
# ApiDeclarationRef – where an API entity is declared
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ApiDeclarationRef:
    """Reference to the declaration site of an API entity in source or SDK."""

    declaration_id: str = ""
    file_path: str = ""
    module: str | None = None
    export_name: str | None = None
    line: int | None = None
    span: tuple[int, int] | None = None
    since_api: str | None = None
    deprecated_since: str | None = None
    parser_level: int = 0

    def to_dict(self) -> dict:
        d: dict[str, object] = {
            "declaration_id": self.declaration_id,
            "file_path": self.file_path,
            "parser_level": self.parser_level,
        }
        if self.module is not None:
            d["module"] = self.module
        if self.export_name is not None:
            d["export_name"] = self.export_name
        if self.line is not None:
            d["line"] = self.line
        if self.span is not None:
            d["span"] = list(self.span)
        if self.since_api is not None:
            d["since_api"] = self.since_api
        if self.deprecated_since is not None:
            d["deprecated_since"] = self.deprecated_since
        return d

    @classmethod
    def from_dict(cls, data: dict) -> ApiDeclarationRef:
        span = data.get("span")
        return cls(
            declaration_id=data.get("declaration_id", ""),
            file_path=data.get("file_path", ""),
            module=data.get("module"),
            export_name=data.get("export_name"),
            line=data.get("line"),
            span=tuple(span) if span is not None else None,
            since_api=data.get("since_api"),
            deprecated_since=data.get("deprecated_since"),
            parser_level=data.get("parser_level", 0),
        )


# ---------------------------------------------------------------------------
# ApiEntity – full representation of a declared API
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ApiEntity:
    """Complete representation of a declared SDK API entity."""

    id: ApiEntityId
    public_name: str = ""
    kind: str = ""  # ApiEntityKind value
    surface: str = "unknown"  # ApiSurfaceKind value
    family: str | None = None
    member_of: str | None = None
    member_name: str | None = None
    module: str | None = None
    language_binding: str | None = None
    since_api: str | None = None
    deprecated_since: str | None = None
    declaration: ApiDeclarationRef | None = None
    stability: str = "unknown"  # stable, deprecated, experimental, internal, unknown
    ambiguity: str = "unambiguous"  # unambiguous, ambiguous, unresolved

    def to_dict(self) -> dict:
        d: dict[str, object] = {
            "id": self.id.to_dict(),
            "public_name": self.public_name,
            "kind": self.kind,
            "surface": self.surface,
            "stability": self.stability,
            "ambiguity": self.ambiguity,
        }
        if self.family is not None:
            d["family"] = self.family
        if self.member_of is not None:
            d["member_of"] = self.member_of
        if self.member_name is not None:
            d["member_name"] = self.member_name
        if self.module is not None:
            d["module"] = self.module
        if self.language_binding is not None:
            d["language_binding"] = self.language_binding
        if self.since_api is not None:
            d["since_api"] = self.since_api
        if self.deprecated_since is not None:
            d["deprecated_since"] = self.deprecated_since
        if self.declaration is not None:
            d["declaration"] = self.declaration.to_dict()
        return d

    @classmethod
    def from_dict(cls, data: dict) -> ApiEntity:
        decl_data = data.get("declaration")
        return cls(
            id=ApiEntityId.from_dict(data["id"]) if "id" in data else ApiEntityId(),
            public_name=data.get("public_name", ""),
            kind=data.get("kind", ""),
            surface=data.get("surface", "unknown"),
            family=data.get("family"),
            member_of=data.get("member_of"),
            member_name=data.get("member_name"),
            module=data.get("module"),
            language_binding=data.get("language_binding"),
            since_api=data.get("since_api"),
            deprecated_since=data.get("deprecated_since"),
            declaration=ApiDeclarationRef.from_dict(decl_data) if decl_data else None,
            stability=data.get("stability", "unknown"),
            ambiguity=data.get("ambiguity", "unambiguous"),
        )


# ---------------------------------------------------------------------------
# EvidenceRef – lightweight evidence provenance reference
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EvidenceRef:
    """Lightweight reference to the provenance of a piece of evidence."""

    edge_id: str | None = None
    file_path: str | None = None
    line: int | None = None
    config_rule_id: str | None = None
    note: str | None = None

    def to_dict(self) -> dict:
        d: dict[str, object] = {}
        if self.edge_id is not None:
            d["edge_id"] = self.edge_id
        if self.file_path is not None:
            d["file_path"] = self.file_path
        if self.line is not None:
            d["line"] = self.line
        if self.config_rule_id is not None:
            d["config_rule_id"] = self.config_rule_id
        if self.note is not None:
            d["note"] = self.note
        return d

    @classmethod
    def from_dict(cls, data: dict) -> EvidenceRef:
        return cls(
            edge_id=data.get("edge_id"),
            file_path=data.get("file_path"),
            line=data.get("line"),
            config_rule_id=data.get("config_rule_id"),
            note=data.get("note"),
        )


# ---------------------------------------------------------------------------
# ApiAlias – an alternative name that resolves to a canonical ApiEntityId
# ---------------------------------------------------------------------------

_ALIAS_KINDS = (
    "import_alias",
    "sdk_alias",
    "config_alias",
    "legacy_name",
    "generated_name",
)
_CONFIDENCE_LEVELS = ("strong", "medium", "weak", "unknown")


@dataclass(frozen=True)
class ApiAlias:
    """An alternative name that resolves to a canonical :class:`ApiEntityId`.

    Aliases never replace canonical identity – they point to it.
    """

    alias: str = ""
    target: ApiEntityId = field(default_factory=ApiEntityId)
    alias_kind: str = "unknown"  # one of _ALIAS_KINDS
    confidence: str = "unknown"  # one of _CONFIDENCE_LEVELS
    evidence: EvidenceRef | None = None

    def to_dict(self) -> dict:
        d: dict[str, object] = {
            "alias": self.alias,
            "target": self.target.to_dict(),
            "alias_kind": self.alias_kind,
            "confidence": self.confidence,
        }
        if self.evidence is not None:
            d["evidence"] = self.evidence.to_dict()
        return d

    @classmethod
    def from_dict(cls, data: dict) -> ApiAlias:
        ev = data.get("evidence")
        return cls(
            alias=data.get("alias", ""),
            target=ApiEntityId.from_dict(data["target"])
            if "target" in data
            else ApiEntityId(),
            alias_kind=data.get("alias_kind", "unknown"),
            confidence=data.get("confidence", "unknown"),
            evidence=EvidenceRef.from_dict(ev) if ev else None,
        )
