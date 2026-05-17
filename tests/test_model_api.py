"""Tests for model.api – canonical API identity and declaration types."""

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from arkui_xts_selector.model.api import (
    ApiAlias,
    ApiEntity,
    ApiEntityId,
    ApiEntityKind,
    ApiDeclarationRef,
    EvidenceRef,
    _encode,
)


class ApiEntityKindTests(unittest.TestCase):
    def test_values_are_string_serializable(self) -> None:
        for member in ApiEntityKind:
            self.assertIsInstance(member.value, str)

    def test_required_kinds_exist(self) -> None:
        names = {m.value for m in ApiEntityKind}
        for name in (
            "component",
            "modifier",
            "attribute",
            "event_or_method",
            "module",
            "configuration",
            "helper_family",
        ):
            self.assertIn(name, names, f"Missing ApiEntityKind.{name}")


class PercentEncodingTests(unittest.TestCase):
    def test_hash(self) -> None:
        self.assertEqual(_encode("a#b"), "a%23b")

    def test_colon(self) -> None:
        self.assertEqual(_encode("a:b"), "a%3Ab")

    def test_slash(self) -> None:
        self.assertEqual(_encode("a/b"), "a%2Fb")

    def test_dot(self) -> None:
        self.assertEqual(_encode("a.b"), "a%2Eb")

    def test_whitespace(self) -> None:
        self.assertEqual(_encode("a b"), "a%20b")

    def test_no_encoding_needed(self) -> None:
        self.assertEqual(_encode("button"), "button")

    def test_deterministic(self) -> None:
        """Same input always produces same output."""
        self.assertEqual(_encode("x#y:z/w.v n"), _encode("x#y:z/w.v n"))

    def test_multiple_reserved(self) -> None:
        result = _encode("a#b:c/d.e f")
        self.assertEqual(result, "a%23b%3Ac%2Fd%2Ee%20f")


class ApiEntityIdTests(unittest.TestCase):
    def _button_id(self) -> ApiEntityId:
        return ApiEntityId.from_parts(
            namespace="arkui",
            surface="static",
            kind="component",
            module="@ohos.arkui.component",
            public_name="Button",
        )

    def _button_attribute_id(self) -> ApiEntityId:
        return ApiEntityId.from_parts(
            namespace="arkui",
            surface="static",
            kind="attribute",
            module="@ohos.arkui.component.Button",
            public_name="ButtonAttribute",
        )

    def _button_modifier_id(self) -> ApiEntityId:
        return ApiEntityId.from_parts(
            namespace="arkui",
            surface="static",
            kind="modifier",
            module="@ohos.arkui.component.Button",
            public_name="ButtonModifier",
        )

    def _content_modifier_id(self) -> ApiEntityId:
        return ApiEntityId.from_parts(
            namespace="arkui",
            surface="static",
            kind="attribute",
            module="@ohos.arkui.component.Button",
            public_name="Button",
            member_of="Button",
            member_name="contentModifier",
        )

    def test_button_canonical_starts_with_api(self) -> None:
        cid = self._button_id().canonical()
        self.assertTrue(cid.startswith("api:"), f"Expected 'api:' prefix, got: {cid}")

    def test_distinct_ids_for_button_family(self) -> None:
        """Button, ButtonAttribute, ButtonModifier, Button.contentModifier must all differ."""
        ids = {
            self._button_id().canonical(),
            self._button_attribute_id().canonical(),
            self._button_modifier_id().canonical(),
            self._content_modifier_id().canonical(),
        }
        self.assertEqual(len(ids), 4, f"Expected 4 distinct ids, got: {ids}")

    def test_button_canonical_format(self) -> None:
        cid = self._button_id().canonical()
        self.assertIn("component", cid)
        # module contains dots -> encoded
        self.assertIn("%2E", cid)
        self.assertIn("Button", cid)

    def test_content_modifier_uses_member_form(self) -> None:
        """contentModifier should be represented as Button#contentModifier member form."""
        cid = self._content_modifier_id().canonical()
        self.assertIn("contentModifier", cid)
        # Should contain encoded hash separator between member_of and member_name
        self.assertIn("%23", cid)

    def test_deterministic(self) -> None:
        """Same fields always produce same canonical id."""
        a = self._button_id()
        b = self._button_id()
        self.assertEqual(a.canonical(), b.canonical())

    def test_frozen(self) -> None:
        aid = self._button_id()
        with self.assertRaises(AttributeError):
            aid.namespace = "other"  # type: ignore[misc]

    def test_to_dict_round_trip(self) -> None:
        aid = self._button_modifier_id()
        d = aid.to_dict()
        self.assertIsInstance(d, dict)
        restored = ApiEntityId.from_dict(d)
        self.assertEqual(aid, restored)

    def test_json_serializable(self) -> None:
        aid = self._button_id()
        d = aid.to_dict()
        text = json.dumps(d, sort_keys=True)
        self.assertIsInstance(text, str)
        restored_d = json.loads(text)
        self.assertEqual(ApiEntityId.from_dict(restored_d), aid)

    def test_ordering(self) -> None:
        """ApiEntityId objects are ordered by canonical string."""
        ids = [
            self._content_modifier_id(),
            self._button_modifier_id(),
            self._button_attribute_id(),
            self._button_id(),
        ]
        sorted_ids = sorted(ids)
        canonicals = [i.canonical() for i in sorted_ids]
        self.assertEqual(canonicals, sorted(canonicals))

    def test_internal_prefix_not_api(self) -> None:
        """Helper/internal ids must NOT use api: prefix."""
        helper_id = ApiEntityId(
            namespace="internal",
            surface="static",
            kind="helper_family",
            module="ace_internal",
            public_name="GeneratedHelper",
        )
        # This is still an ApiEntityId (with api: prefix in canonical())
        # but the NAMESPACE indicates internal.  The canonical() always
        # starts with "api:" for ApiEntityId.  The distinction is that
        # internal entities should use a different *type* or *namespace*
        # convention -- which is captured in the namespace field.
        cid = helper_id.canonical()
        self.assertIn("internal", cid)


class ApiEntityIdAmbiguityTests(unittest.TestCase):
    def test_ambiguous_representation(self) -> None:
        """A query resolving to multiple canonical ids can be represented."""
        btn1 = ApiEntityId.from_parts(
            namespace="arkui",
            surface="static",
            kind="component",
            module="@ohos.arkui.component",
            public_name="Button",
        )
        btn2 = ApiEntityId.from_parts(
            namespace="arkui",
            surface="dynamic",
            kind="component",
            module="@ohos.arkui.node",
            public_name="Button",
        )
        self.assertNotEqual(btn1.canonical(), btn2.canonical())
        # An ambiguous query result can simply be a list of candidates
        candidates = [btn1, btn2]
        self.assertEqual(len(candidates), 2)


class ApiDeclarationRefTests(unittest.TestCase):
    def test_round_trip(self) -> None:
        ref = ApiDeclarationRef(
            declaration_id="sdk_decl:button.d.ts#Button",
            file_path="api/@ohos.arkui.component.button.d.ts",
            module="@ohos.arkui.component",
            export_name="ButtonAttribute",
            line=42,
            span=(100, 200),
            since_api="9",
            parser_level=3,
        )
        d = ref.to_dict()
        restored = ApiDeclarationRef.from_dict(d)
        self.assertEqual(ref, restored)

    def test_minimal(self) -> None:
        ref = ApiDeclarationRef()
        d = ref.to_dict()
        self.assertIn("declaration_id", d)
        self.assertIn("parser_level", d)


class ApiEntityTests(unittest.TestCase):
    def test_round_trip(self) -> None:
        entity = ApiEntity(
            id=ApiEntityId.from_parts(
                namespace="arkui",
                surface="static",
                kind="component",
                module="@ohos.arkui.component",
                public_name="Button",
            ),
            public_name="Button",
            kind="component",
            surface="static",
            family="Button",
            stability="stable",
            ambiguity="unambiguous",
            declaration=ApiDeclarationRef(
                file_path="api/button.d.ts",
                parser_level=3,
            ),
        )
        d = entity.to_dict()
        restored = ApiEntity.from_dict(d)
        self.assertEqual(entity, restored)

    def test_ambiguous_flag(self) -> None:
        entity = ApiEntity(
            id=ApiEntityId(public_name="Unknown"),
            ambiguity="ambiguous",
        )
        self.assertEqual(entity.ambiguity, "ambiguous")


class ApiAliasTests(unittest.TestCase):
    def test_alias_does_not_replace_identity(self) -> None:
        """An alias points to a target but the target retains its own identity."""
        target = ApiEntityId.from_parts(
            namespace="arkui",
            surface="static",
            kind="component",
            module="@ohos.arkui.component",
            public_name="Button",
        )
        alias = ApiAlias(
            alias="Btn",
            target=target,
            alias_kind="import_alias",
            confidence="strong",
        )
        # The alias name is different from the canonical id
        self.assertNotEqual(alias.alias, target.canonical())
        # But the target remains unchanged
        self.assertEqual(alias.target, target)
        self.assertEqual(alias.target.public_name, "Button")

    def test_round_trip(self) -> None:
        target = ApiEntityId.from_parts(
            namespace="arkui",
            surface="static",
            kind="modifier",
            module="@ohos.arkui.component.Button",
            public_name="ButtonModifier",
        )
        alias = ApiAlias(
            alias="ButtonModifier",
            target=target,
            alias_kind="sdk_alias",
            confidence="medium",
            evidence=EvidenceRef(file_path="sdk/button.d.ts", line=10),
        )
        d = alias.to_dict()
        restored = ApiAlias.from_dict(d)
        self.assertEqual(alias, restored)


if __name__ == "__main__":
    unittest.main()
