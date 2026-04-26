from __future__ import annotations

import re
from dataclasses import dataclass, field


IMPORT_RE = re.compile(r"""from\s+['"]([^'"]+)['"]""")
IMPORT_BINDING_RE = re.compile(r"""import\s*\{([^}]*)\}\s*from\s*['"]([^'"]+)['"]""", re.S)
DEFAULT_IMPORT_RE = re.compile(r"""import\s+([A-Za-z_][A-Za-z0-9_]*)\s+from\s+['"]([^'"]+)['"]""")
IDENTIFIER_CALL_RE = re.compile(r"""\b([A-Z][A-Za-z0-9_]*)\s*\(""")
MEMBER_CALL_RE = re.compile(r"""\.([A-Za-z_][A-Za-z0-9_]*)\s*\(""")
TYPE_MEMBER_CALL_RE = re.compile(r"""\b([A-Z][A-Za-z0-9_]*)\.([A-Za-z_][A-Za-z0-9_]*)\s*\(""")
WORD_RE = re.compile(r"""\b[A-Za-z_][A-Za-z0-9_]{2,}\b""")
PARAM_TYPE_RE = re.compile(r"""[\(,]\s*([A-Za-z_][A-Za-z0-9_]*)\s*:\s*([A-Z][A-Za-z0-9_]*)\b""")
VAR_TYPE_RE = re.compile(r"""\b(?:const|let|var)\s+([A-Za-z_][A-Za-z0-9_]*)\s*:\s*([A-Z][A-Za-z0-9_]*)\b""")
MEMBER_ACCESS_RE = re.compile(r"""\b([A-Za-z_][A-Za-z0-9_]*)\.([A-Za-z_][A-Za-z0-9_]*)\b(?!\s*\()""")
TYPED_OBJECT_LITERAL_RE = re.compile(
    r"""\b(?:const|let|var)\s+[A-Za-z_][A-Za-z0-9_]*\s*:\s*([A-Z][A-Za-z0-9_]*)\s*=\s*\{(?P<body>[^{}]*)\}""",
    re.S,
)
OBJECT_LITERAL_FIELD_RE = re.compile(r"""\b([A-Za-z_][A-Za-z0-9_]*)\s*:""")
TYPED_ATTRIBUTE_MODIFIER_RE = re.compile(r"""AttributeModifier<([A-Za-z_][A-Za-z0-9_]*)Attribute>""")
EXTENDS_MODIFIER_RE = re.compile(r"""extends\s+([A-Za-z_][A-Za-z0-9_]*)Modifier\b""")

GENERIC_TYPED_FIELD_NAMES = {
    "x",
    "y",
    "z",
    "dx",
    "dy",
    "dz",
    "type",
    "id",
    "name",
    "value",
    "index",
    "length",
    "size",
    "status",
}
STRUCTURAL_TYPED_CALLBACK_TYPES = {
    "baseevent",
    "layoutable",
    "measurable",
}

# New patterns for Phase 2
# Destructuring: const { field1, field2 } = typedObject
DESTRUCTURING_RE = re.compile(
    r"""\b(?:const|let|var)\s+\{([^}]*)\}\s*=\s*([A-Za-z_][A-Za-z0-9_]*)\b""",
    re.S,
)
# Rebinding: let x = obj; then x.field
REBIND_RE = re.compile(
    r"""\b(?:const|let|var)\s+([A-Za-z_][A-Za-z0-9_]*)\s*=\s*([A-Za-z_][A-Za-z0-9_]*)\b""",
)
# Proxy bind methods: proxy.bindPopup(content), proxy.bindSheet(menu)
PROXY_BIND_RE = re.compile(
    r"""\b([A-Za-z_][A-Za-z0-9_]*)\.(bind[A-Z][A-Za-z0-9_]*)\s*\(""",
)
# @kit.ArkUI aggregate import
KIT_AGGREGATE_IMPORT_RE = re.compile(
    r"""from\s+['"]@kit\.ArkUI['"]""",
)
# EventType.field: ClickEvent.globalX, KeyEvent.keyCode
EVENT_TYPE_FIELD_RE = re.compile(
    r"""\b(ClickEvent|KeyEvent|TouchEvent|LongPressEvent|PanGesture|PinchGesture|RotationGesture|SwipeGesture)\.([A-Za-z_][A-Za-z0-9_]*)\b(?!\s*\()""",
)


def compact_token(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


@dataclass
class ConsumerSemantics:
    imports: set[str] = field(default_factory=set)
    imported_symbols: set[str] = field(default_factory=set)
    identifier_calls: set[str] = field(default_factory=set)
    member_calls: set[str] = field(default_factory=set)
    type_member_calls: set[str] = field(default_factory=set)
    typed_field_accesses: set[str] = field(default_factory=set)
    typed_modifier_bases: set[str] = field(default_factory=set)
    words: set[str] = field(default_factory=set)
    # Phase 2 additions
    evidence_kinds: dict[str, str] = field(default_factory=dict)
    # Maps extracted hints -> evidence kind
    # kind values: "import", "type_member_call", "field_read", "field_write",
    #   "typed_object_literal_write", "callback_bind", "destructuring",
    #   "rebinding", "proxy_bind", "event_type_field", "kit_aggregate_import"
    destructuring_fields: dict[str, str] = field(default_factory=dict)
    # Maps source variable -> set of bound field names from destructuring
    rebinding_map: dict[str, str] = field(default_factory=dict)
    # Maps rebound variable -> original variable
    proxy_binds: set[str] = field(default_factory=set)
    # bind* method names found in proxy files
    event_type_fields: set[str] = field(default_factory=set)
    # ClickEvent.x, KeyEvent.keyCode etc.
    is_kit_aggregate_import: bool = False
    # True if file imports from @kit.ArkUI


def extract_typed_field_accesses(text: str) -> set[str]:
    bindings: dict[str, tuple[str, str]] = {}
    for name, type_name in PARAM_TYPE_RE.findall(text):
        bindings[str(name).strip()] = (str(type_name).strip(), "param")
    for name, type_name in VAR_TYPE_RE.findall(text):
        bindings[str(name).strip()] = (str(type_name).strip(), "var")

    accesses: set[str] = set()
    for variable, field_name in MEMBER_ACCESS_RE.findall(text):
        binding = bindings.get(str(variable).strip())
        if not binding:
            continue
        type_name, origin = binding
        field = str(field_name).strip()
        field_token = compact_token(field)
        if not field or field_token in GENERIC_TYPED_FIELD_NAMES:
            continue
        if origin == "param" and compact_token(type_name) in STRUCTURAL_TYPED_CALLBACK_TYPES:
            continue
        accesses.add(f"{type_name}.{field}")

    for type_name, body in TYPED_OBJECT_LITERAL_RE.findall(text):
        for field_name in OBJECT_LITERAL_FIELD_RE.findall(body):
            field = str(field_name).strip()
            if not field or compact_token(field) in GENERIC_TYPED_FIELD_NAMES:
                continue
            accesses.add(f"{type_name}.{field}")
    return accesses


def extract_consumer_semantics(text: str) -> ConsumerSemantics:
    imported_symbols: set[str] = set()
    typed_modifier_bases: set[str] = set()
    for match in IMPORT_BINDING_RE.finditer(text):
        for part in match.group(1).split(","):
            normalized = part.strip()
            alias_parts = [item.strip() for item in normalized.split(" as ", 1)]
            token = alias_parts[1] if len(alias_parts) == 2 and alias_parts[1] else alias_parts[0]
            if token:
                imported_symbols.add(token)
    for match in DEFAULT_IMPORT_RE.finditer(text):
        imported_symbols.add(match.group(1))
    for raw in TYPED_ATTRIBUTE_MODIFIER_RE.findall(text):
        base = compact_token(raw)
        if base:
            typed_modifier_bases.add(base)
    for raw in EXTENDS_MODIFIER_RE.findall(text):
        base = compact_token(raw)
        if base:
            typed_modifier_bases.add(base)

    # Phase 2: extract destructuring patterns
    destructuring_fields: dict[str, set[str]] = {}
    for match in DESTRUCTURING_RE.finditer(text):
        fields_raw = match.group(1)
        source_var = match.group(2)
        fields = {f.strip() for f in fields_raw.split(",") if f.strip()}
        if fields:
            destructuring_fields[source_var] = fields

    # Phase 2: extract rebinding patterns
    rebinding_map: dict[str, str] = {}
    for match in REBIND_RE.finditer(text):
        local_var = match.group(1)
        original_var = match.group(2)
        rebinding_map[local_var] = original_var

    # Phase 2: extract proxy bind patterns
    proxy_binds: set[str] = set()
    for match in PROXY_BIND_RE.finditer(text):
        proxy_binds.add(match.group(2))

    # Phase 2: extract event type field patterns
    event_type_fields: set[str] = set()
    for match in EVENT_TYPE_FIELD_RE.finditer(text):
        event_type = match.group(1)
        field_name = match.group(2)
        event_type_fields.add(f"{event_type}.{field_name}")

    # Phase 2: detect @kit.ArkUI aggregate import
    is_kit_aggregate = bool(KIT_AGGREGATE_IMPORT_RE.search(text))

    # Build evidence_kinds mapping
    evidence_kinds: dict[str, str] = {}
    for sym in imported_symbols:
        evidence_kinds[sym] = "import"
    for tm in TYPE_MEMBER_CALL_RE.findall(text):
        key = f"{tm[0]}.{tm[1]}"
        evidence_kinds[key] = "type_member_call"
    for field_access in extract_typed_field_accesses(text):
        evidence_kinds[field_access] = "field_write"
    for etf in event_type_fields:
        evidence_kinds[etf] = "event_type_field"

    return ConsumerSemantics(
        imports=set(IMPORT_RE.findall(text)),
        imported_symbols=imported_symbols,
        identifier_calls=set(IDENTIFIER_CALL_RE.findall(text)),
        member_calls=set(MEMBER_CALL_RE.findall(text)),
        type_member_calls={f"{owner}.{member}" for owner, member in TYPE_MEMBER_CALL_RE.findall(text)},
        typed_field_accesses=extract_typed_field_accesses(text),
        typed_modifier_bases=typed_modifier_bases,
        words={word.lower() for word in WORD_RE.findall(text)},
        evidence_kinds=evidence_kinds,
        destructuring_fields={k: v for k, v in destructuring_fields.items()},
        rebinding_map=rebinding_map,
        proxy_binds=proxy_binds,
        event_type_fields=event_type_fields,
        is_kit_aggregate_import=is_kit_aggregate,
    )
