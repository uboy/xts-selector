"""Demo app snippet generator for SDK-visible ArkUI components.

Generates minimal ArkUI demo app snippets for SDK-visible APIs to help
developers understand how to write apps for testing changed interfaces.

Non-negotiable safety rules:
- Only generates snippets for SDK-visible component names (public API identity).
- Internal C++ names (e.g. ButtonModifier as a public API identity) are refused.
- If signature is unknown, generates a TODO placeholder — never invents signatures.
- Does NOT affect selector buckets or production selector behavior.
- false_must_run remains 0.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# Known SDK-visible ArkUI component families
# Derived from interface_sdk-js/api/arkui/component/*.static.d.ets filenames
# and the _SDK_FILENAME_SYMBOL_OVERRIDE table in api_lineage.py.
# This set is the public API identity — NOT internal C++ modifier names.
# ---------------------------------------------------------------------------
KNOWN_SDK_COMPONENTS: frozenset[str] = frozenset(
    {
        "AlphabetIndexer",
        "Badge",
        "Button",
        "CalendarPicker",
        "Canvas",
        "Checkbox",
        "Circle",
        "Column",
        "DataPanel",
        "DatePicker",
        "Ellipse",
        "FlowItem",
        "Grid",
        "GridCol",
        "GridItem",
        "GridRow",
        "Image",
        "ImageAnimator",
        "Line",
        "List",
        "ListItem",
        "ListItemGroup",
        "LoadingProgress",
        "MenuItem",
        "NavDestination",
        "Panel",
        "PatternLock",
        "Progress",
        "QRCode",
        "Radio",
        "Rect",
        "Refresh",
        "RelativeContainer",
        "RichEditor",
        "RichText",
        "Row",
        "Scroll",
        "ScrollBar",
        "Search",
        "Select",
        "SideBarContainer",
        "Slider",
        "Span",
        "Stepper",
        "StepperItem",
        "SymbolGlyph",
        "TabContent",
        "Tabs",
        "Text",
        "TextArea",
        "TextClock",
        "TextInput",
        "TextTimer",
        "TimePicker",
        "Toggle",
        "WaterFlow",
        "Web",
        "XComponent",
    }
)

# Normalized (lowercase) lookup for case-insensitive matching
_SDK_COMPONENT_LOWER: dict[str, str] = {c.lower(): c for c in KNOWN_SDK_COMPONENTS}

# Known internal C++ modifier suffix patterns that are NOT public SDK identity
_INTERNAL_MODIFIER_SUFFIX = "Modifier"

# Typical attribute method examples for template generation
_ATTRIBUTE_EXAMPLES: dict[str, dict[str, str]] = {
    "Button": {"method": "fontSize", "value": "16", "chain": ".fontSize(16)"},
    "Slider": {"method": "min", "value": "0", "chain": ".min(0).max(100).value(50)"},
    "TextInput": {"method": "placeholder", "value": "'Enter text...'", "chain": ".placeholder('Enter text...')"},
    "Text": {"method": "fontSize", "value": "16", "chain": ".fontSize(16).fontColor('#333333')"},
    "Image": {"method": "width", "value": "200", "chain": ".width(200).height(200)"},
    "Toggle": {"method": "selectedColor", "value": "'#007DFF'", "chain": ".selectedColor('#007DFF')"},
    "Progress": {"method": "value", "value": "50", "chain": ".value(50)"},
    "Checkbox": {"method": "select", "value": "true", "chain": ".select(true)"},
    "Radio": {"method": "value", "value": "'option1'", "chain": ".value('option1')"},
    "Select": {"method": "value", "value": "0", "chain": ".value(0)"},
    "Search": {"method": "placeholder", "value": "'Search...'", "chain": ".placeholder('Search...')"},
    "TextArea": {"method": "placeholder", "value": "'Enter text...'", "chain": ".placeholder('Enter text...')"},
}

# Default attribute fallback
_DEFAULT_ATTRIBUTE = {"method": "width", "value": "200", "chain": ".width(200).height(80)"}

# Event handler templates per component (member used for .onChange / .onClick)
_EVENT_EXAMPLES: dict[str, dict[str, str]] = {
    "Button": {
        "event": "onClick",
        "handler": ".onClick(() => { console.log('Button clicked'); })",
    },
    "Slider": {
        "event": "onChange",
        "handler": ".onChange((value: number) => { console.log('Slider value:', value); })",
    },
    "TextInput": {
        "event": "onChange",
        "handler": ".onChange((value: string) => { console.log('TextInput value:', value); })",
    },
    "Toggle": {
        "event": "onChange",
        "handler": ".onChange((isOn: boolean) => { console.log('Toggle:', isOn); })",
    },
    "Checkbox": {
        "event": "onChange",
        "handler": ".onChange((value: boolean) => { console.log('Checkbox:', value); })",
    },
    "Radio": {
        "event": "onChange",
        "handler": ".onChange((value: boolean) => { console.log('Radio:', value); })",
    },
    "Search": {
        "event": "onSubmit",
        "handler": ".onSubmit((searchValue: string) => { console.log('Search:', searchValue); })",
    },
    "Select": {
        "event": "onSelect",
        "handler": ".onSelect((index: number, value: string) => { console.log('Select:', index, value); })",
    },
    "TextArea": {
        "event": "onChange",
        "handler": ".onChange((value: string) => { console.log('TextArea value:', value); })",
    },
}

# Default event fallback
_DEFAULT_EVENT = {
    "event": "onClick",
    "handler": ".onClick(() => { console.log('Component interacted'); })",
}

# Construction argument templates
_CONSTRUCTION_ARGS: dict[str, str] = {
    "Button": "({ type: ButtonType.Normal }) { Text('Click me') }",
    "TextInput": "({ placeholder: 'Enter text...' })",
    "TextArea": "({ placeholder: 'Enter text...' })",
    "Slider": "({ value: 50, min: 0, max: 100, style: SliderStyle.OutSet })",
    "Toggle": "({ type: ToggleType.Button, isOn: false }) { Text('Toggle') }",
    "Image": "($r('app.media.icon'))",
    "Text": "('Hello, ArkUI!')",
    "Checkbox": "({ name: 'checkbox', group: 'checkboxGroup' })",
    "Radio": "({ value: 'option1', group: 'radioGroup' })",
    "Select": "([{ value: 'Option 1' }, { value: 'Option 2' }])",
    "Progress": "({ value: 50, total: 100, type: ProgressType.Linear })",
    "LoadingProgress": "()",
    "QRCode": "('https://example.com')",
    "PatternLock": "(new PatternLockController())",
    "DataPanel": "({ values: [25, 25, 25, 25], max: 100, type: DataPanelType.Line })",
    "Badge": "({ count: 1, position: BadgePosition.RightTop, style: { color: '#fff', fontSize: 10, badgeSize: 16, badgeColor: '#FA2A2D' } }) { Text('Badge') }",
    "Search": "({ value: '', placeholder: 'Search...' })",
    "TextClock": "(new TextClockController())",
    "TextTimer": "({ isCountDown: true, count: 30000, controller: new TextTimerController() })",
    "Web": "({ src: 'https://example.com', controller: new WebController() })",
    "XComponent": "({ id: 'xcomponent', type: 'surface', controller: new XComponentController() })",
    "Canvas": "(new CanvasRenderingContext2D(new RenderingContextSettings(true)))",
}

_DEFAULT_CONSTRUCTION = "()"


@dataclass
class DemoSnippet:
    """Result of demo snippet generation."""

    api_name: str
    sdk_visible: bool
    snippet: str
    imports: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)


def _resolve_component_name(api_name: str) -> Optional[str]:
    """Return the canonical SDK component name, or None if not SDK-visible."""
    # Exact match
    if api_name in KNOWN_SDK_COMPONENTS:
        return api_name
    # Case-insensitive match
    lower = api_name.lower()
    if lower in _SDK_COMPONENT_LOWER:
        return _SDK_COMPONENT_LOWER[lower]
    return None


def _is_internal_modifier(api_name: str) -> bool:
    """Return True if name looks like an internal C++ modifier (not a public SDK identity).

    E.g. ButtonModifier, SliderModifier — these are internal names. The public
    API identity is Button, Slider etc.
    NOTE: names ending in Modifier that are NOT in KNOWN_SDK_COMPONENTS are
    considered internal.
    """
    if not api_name.endswith(_INTERNAL_MODIFIER_SUFFIX):
        return False
    # If the full name (e.g. "SideBarContainerModifier") is somehow in known set, allow it.
    if api_name in KNOWN_SDK_COMPONENTS:
        return False
    return True


def _build_component_creation_snippet(component: str) -> str:
    """Generate a full @Entry @Component struct with component in build()."""
    args = _CONSTRUCTION_ARGS.get(component, _DEFAULT_CONSTRUCTION)
    return f"""\
import {{ {component} }} from '@ohos.arkui.node';

@Entry
@Component
struct Demo{component} {{
  build() {{
    Column() {{
      {component}{args}
    }}
    .width('100%')
    .height('100%')
  }}
}}
"""


def _build_attribute_snippet(component: str, member: Optional[str]) -> str:
    """Generate a component snippet with an attribute method chain."""
    args = _CONSTRUCTION_ARGS.get(component, _DEFAULT_CONSTRUCTION)
    if member:
        attr_chain = f".{member}(/* TODO: provide appropriate value */)"
        attr_desc = member
    else:
        example = _ATTRIBUTE_EXAMPLES.get(component, _DEFAULT_ATTRIBUTE)
        attr_chain = example["chain"]
        attr_desc = example["method"]

    return f"""\
import {{ {component} }} from '@ohos.arkui.node';

@Entry
@Component
struct Demo{component}Attribute {{
  build() {{
    Column() {{
      {component}{args}
        {attr_chain}
    }}
    .width('100%')
    .height('100%')
  }}
}}
// Tests attribute: {attr_desc}
"""


def _build_event_snippet(component: str, member: Optional[str]) -> str:
    """Generate a component snippet with an event/method handler."""
    args = _CONSTRUCTION_ARGS.get(component, _DEFAULT_CONSTRUCTION)
    if member:
        handler = f".{member}((...args) => {{ console.log('{member} called', args); }})"
        event_name = member
    else:
        example = _EVENT_EXAMPLES.get(component, _DEFAULT_EVENT)
        handler = example["handler"]
        event_name = example["event"]

    return f"""\
import {{ {component} }} from '@ohos.arkui.node';

@Entry
@Component
struct Demo{component}Event {{
  build() {{
    Column() {{
      {component}{args}
        {handler}
    }}
    .width('100%')
    .height('100%')
  }}
}}
// Tests event/method: {event_name}
"""


def generate_demo_snippet(
    api_name: str,
    usage_kind: str = "component_creation",
    member: Optional[str] = None,
) -> DemoSnippet:
    """Generate a minimal ArkUI demo app snippet for an SDK-visible API.

    Args:
        api_name: The public SDK component name (e.g. "Button", "Slider").
        usage_kind: One of "component_creation", "attribute", "event_or_method".
                    Any other value is treated as "unknown".
        member: Optional specific attribute or event name to demonstrate.

    Returns:
        DemoSnippet with sdk_visible=True and a valid snippet, OR
        DemoSnippet with sdk_visible=False and explanation in limitations if
        the api_name is not SDK-visible.
    """
    # Safety check: refuse internal C++ modifier names
    if _is_internal_modifier(api_name):
        return DemoSnippet(
            api_name=api_name,
            sdk_visible=False,
            snippet="",
            imports=[],
            limitations=[
                f"'{api_name}' appears to be an internal C++ modifier name, not a public SDK API identity. "
                f"The public SDK component name is '{api_name[:-len(_INTERNAL_MODIFIER_SUFFIX)]}'. "
                "Use the component name (e.g. 'Button') as api_name, not the modifier name."
            ],
        )

    # Resolve component name
    component = _resolve_component_name(api_name)
    if component is None:
        return DemoSnippet(
            api_name=api_name,
            sdk_visible=False,
            snippet="",
            imports=[],
            limitations=[
                f"'{api_name}' is not a known SDK-visible ArkUI component. "
                "Cannot generate a demo snippet without a verified SDK declaration. "
                "If this is a new component, add it to KNOWN_SDK_COMPONENTS after "
                "verifying its declaration in interface_sdk-js/api/arkui/component/."
            ],
        )

    # Generate snippet based on usage_kind
    if usage_kind == "component_creation":
        snippet = _build_component_creation_snippet(component)
        limitations = []
        if component not in _CONSTRUCTION_ARGS:
            limitations.append(
                f"Construction args for {component} are not in the known table; "
                "default '()' was used. Verify the actual constructor signature in "
                "interface_sdk-js/api/arkui/component/"
                f"{component.lower()}.static.d.ets."
            )
        return DemoSnippet(
            api_name=component,
            sdk_visible=True,
            snippet=snippet,
            imports=[f"import {{ {component} }} from '@ohos.arkui.node';"],
            limitations=limitations,
        )

    elif usage_kind == "attribute":
        snippet = _build_attribute_snippet(component, member)
        limitations = []
        if member:
            limitations.append(
                f"Attribute value for '.{member}()' is a TODO placeholder. "
                "Provide the correct value per the SDK type signature."
            )
        return DemoSnippet(
            api_name=component,
            sdk_visible=True,
            snippet=snippet,
            imports=[f"import {{ {component} }} from '@ohos.arkui.node';"],
            limitations=limitations,
        )

    elif usage_kind == "event_or_method":
        snippet = _build_event_snippet(component, member)
        limitations = []
        if member:
            limitations.append(
                f"Handler signature for '.{member}()' uses a generic spread args placeholder. "
                "Update the handler to match the actual event/callback type."
            )
        return DemoSnippet(
            api_name=component,
            sdk_visible=True,
            snippet=snippet,
            imports=[f"import {{ {component} }} from '@ohos.arkui.node';"],
            limitations=limitations,
        )

    else:
        return DemoSnippet(
            api_name=api_name,
            sdk_visible=False,
            snippet="",
            imports=[],
            limitations=[
                f"Unknown usage_kind '{usage_kind}'. "
                "Supported values: 'component_creation', 'attribute', 'event_or_method'."
            ],
        )
