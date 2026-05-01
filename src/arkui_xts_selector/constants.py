"""Regex patterns, constant dicts, sentinel sets, choice tuples, and display constants."""

from __future__ import annotations

import re


# ---------------------------------------------------------------------------
# Choice tuples (used by argparse)
# ---------------------------------------------------------------------------
RELEVANCE_MODE_CHOICES = ("all", "balanced", "strict")
PR_SOURCE_CHOICES = ("auto", "api", "git")
GIT_HOST_KIND_CHOICES = ("auto", "gitcode", "codehub")
CODEHUB_SECTION_NAMES = ("codehub", "codehub-y", "cr-y.codehub", "opencodehub")


# ---------------------------------------------------------------------------
# Display limits
# ---------------------------------------------------------------------------
HUMAN_OPTIONAL_DUPLICATE_DISPLAY_LIMIT = 20
HUMAN_RUN_TARGET_DISPLAY_LIMIT = 10
HUMAN_COMPACT_CHANGED_FILE_THRESHOLD = 8
PROGRESS_AGGREGATE_CHANGED_FILE_THRESHOLD = 6
PROGRESS_AGGREGATE_CHANGED_FILE_STEP = 5


# ---------------------------------------------------------------------------
# Default changed-file exclusion rules
# ---------------------------------------------------------------------------
DEFAULT_CHANGED_FILE_EXCLUSION_RULES = {
    "rules": [
        {
            "id": "native_unit_tests_root",
            "category": "non_xts_local_tests",
            "path_prefix": "test/unittest/",
            "description": "Native/unit-test sources are implementation-side checks, not user-facing XTS coverage targets.",
            "how_to_identify": [
                "Path starts with test/unittest/.",
                "File belongs to local unit-test coverage rather than XTS ACTS suites.",
            ],
        },
        {
            "id": "ace_engine_unit_tests_mirror",
            "category": "non_xts_local_tests",
            "path_prefix": "foundation/arkui/ace_engine/test/unittest/",
            "description": "Mirrored ace_engine unit-test directories should not drive XTS selection.",
            "how_to_identify": [
                "Path starts with foundation/arkui/ace_engine/test/unittest/.",
                "Content is repo-local unit testing, not external ArkUI XTS behavior coverage.",
            ],
        },
        {
            "id": "mock_sources_root",
            "category": "non_product_test_support",
            "path_prefix": "test/mock/",
            "description": "Mock infrastructure changes should not directly select product-facing XTS suites.",
            "how_to_identify": [
                "Path starts with test/mock/.",
                "Files provide fake or stub test infrastructure rather than production behavior.",
            ],
        },
        {
            "id": "ace_engine_mock_sources_mirror",
            "category": "non_product_test_support",
            "path_prefix": "foundation/arkui/ace_engine/test/mock/",
            "description": "Mirrored ace_engine mock sources are support code and should be excluded from XTS changed-file analysis.",
            "how_to_identify": [
                "Path starts with foundation/arkui/ace_engine/test/mock/.",
                "Files are mock/stub support code rather than product behavior.",
            ],
        },
        {
            "id": "generated_advanced_ui_assembled_wrappers",
            "category": "generated_wrapper_noise",
            "path_prefix": "foundation/arkui/ace_engine/advanced_ui_component_static/assembled_advanced_ui_component/",
            "description": "Generated assembled advanced-ui ETS wrappers import broad generic ArkUI symbols and can swamp the selector with unrelated XTS suites.",
            "how_to_identify": [
                "Path is under foundation/arkui/ace_engine/advanced_ui_component_static/assembled_advanced_ui_component/.",
                "File is an assembled @ohos.arkui.advanced.* ETS wrapper rather than the authored source under advanced_ui_component/<component>/source/.",
                "The wrapper re-exports or imports broad generic ArkUI component symbols such as Text, Image, Button, Scroll, Stack, and similar shared primitives.",
            ],
        },
    ]
}


# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------
IMPORT_RE = re.compile(r"""from\s+['"]([^'"]+)['"]""")
IMPORT_BINDING_RE = re.compile(r"""import\s*\{([^}]*)\}\s*from\s*['"]([^'"]+)['"]""", re.S)
DEFAULT_IMPORT_RE = re.compile(r"""import\s+([A-Za-z_][A-Za-z0-9_]*)\s+from\s+['"]([^'"]+)['"]""")
IDENTIFIER_CALL_RE = re.compile(r"""\b([A-Z][A-Za-z0-9_]*)\s*\(""")
MEMBER_CALL_RE = re.compile(r"""\.([A-Za-z_][A-Za-z0-9_]*)\s*\(""")
WORD_RE = re.compile(r"""\b[A-Za-z_][A-Za-z0-9_]{2,}\b""")
PARAM_TYPE_RE = re.compile(r"""[\(,]\s*([A-Za-z_][A-Za-z0-9_]*)\s*:\s*([A-Z][A-Za-z0-9_]*)\b""")
VAR_TYPE_RE = re.compile(r"""\b(?:const|let|var)\s+([A-Za-z_][A-Za-z0-9_]*)\s*:\s*([A-Z][A-Za-z0-9_]*)\b""")
MEMBER_ACCESS_RE = re.compile(r"""\b([A-Za-z_][A-Za-z0-9_]*)\.([A-Za-z_][A-Za-z0-9_]*)\b(?!\s*\()""")
TYPED_OBJECT_LITERAL_RE = re.compile(
    r"""\b(?:const|let|var)\s+[A-Za-z_][A-Za-z0-9_]*\s*:\s*([A-Z][A-Za-z0-9_]*)\s*=\s*\{(?P<body>[^{}]*)\}""",
    re.S,
)
OBJECT_LITERAL_FIELD_RE = re.compile(r"""\b([A-Za-z_][A-Za-z0-9_]*)\s*:""")
OHOS_MODULE_RE = re.compile(r"""@ohos\.[A-Za-z0-9._]+""")
CPP_IDENTIFIER_RE = re.compile(r"""\b[A-Z][A-Za-z0-9_]{2,}\b""")
TYPE_MEMBER_CALL_RE = re.compile(r"""\b([A-Z][A-Za-z0-9_]*)\.([A-Za-z_][A-Za-z0-9_]*)\s*\(""")
EXPORT_CLASS_RE = re.compile(r"""\bexport\s+class\s+([A-Z][A-Za-z0-9_]*)\b""")
EXPORT_INTERFACE_RE = re.compile(r"""\bexport\s+interface\s+([A-Z][A-Za-z0-9_]*)\b""")
EXPORT_INTERFACE_BLOCK_RE = re.compile(
    r"""\bexport\s+(?:declare\s+)?interface\s+([A-Z][A-Za-z0-9_]*)[^{]*\{(?P<body>.*?)\}""",
    re.S,
)
INTERFACE_PROPERTY_RE = re.compile(r"""^\s*(?:readonly\s+)?([A-Za-z_][A-Za-z0-9_]*)\??\s*:\s*[^;{}]+;?\s*$""", re.M)
INTERFACE_METHOD_RE = re.compile(r"""^\s*(?:readonly\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*\([^;{}]*\)\s*:\s*[^;]+;?\s*$""", re.M)
PUBLIC_METHOD_RE = re.compile(r"""\bpublic\s+(?:static\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*\(""")
UNIFIED_DIFF_HUNK_RE = re.compile(r"""^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@""", re.M)
GENERATED_ACCESSOR_NAMESPACE_RE = re.compile(r"""GeneratedModifier::([A-Za-z_][A-Za-z0-9_]*)Accessor\b""")
GET_ACCESSOR_RE = re.compile(r"""\bGet([A-Za-z_][A-Za-z0-9_]*)Accessor\s*\(""")
PEER_INCLUDE_RE = re.compile(r"#include\s+\"[^\"]*/([a-z0-9_]+)_peer\.h\"")
DYNAMIC_MODULE_RE = re.compile(r"""GetDynamicModule\("([A-Za-z0-9_]+)"\)""")
DECLARE_INTERFACE_RE = re.compile(r"""\bdeclare\s+interface\s+([A-Z][A-Za-z0-9_]*)\b""")
DECLARE_TYPE_RE = re.compile(r"""\bdeclare\s+(?:type|typedef)\s+([A-Z][A-Za-z0-9_]*)\b""")
DECLARE_FUNCTION_RE = re.compile(r"""\bdeclare\s+function\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(""")
DECLARE_MODULE_RE = re.compile(r"""declare\s+module\s+['"]([^'"]+)['"]""")
TS_EXPORT_TYPE_RE = re.compile(r"""\bexport\s+(?:type|interface|class|const|function)\s+([A-Za-z_][A-Za-z0-9_]*)\b""")
CPP_FUNCTION_DEF_RE = re.compile(
    r"""(?:(?:const\s+)?(?:void|bool|int|auto|static|RefPtr|AceType|"""
    r"""std::(?:optional|string|pair|shared_ptr|unique_ptr)|"""
    r"""Color|Dimension|Offset|Size|Rect|PointF|Matrix4|Matrix44|"""
    r"""std::pair|std::tuple|std::function|"""
    r"""std::variant|std::monostate|std::any|"""
    r"""Template\s*<[^>]*>|"""
    r"""typename\s+\w+)\s+)?"""
    r"""(\b[A-Z][A-Za-z0-9_]{2,}\b)\s*\("""
)
CPP_METHOD_DEF_RE = re.compile(r"""(\b[A-Z][A-Za-z0-9_]{2,})::([A-Z][A-Za-z0-9_]{2,})\s*\(""")
TYPED_ATTRIBUTE_MODIFIER_RE = re.compile(r"""AttributeModifier<([A-Za-z_][A-Za-z0-9_]*)Attribute>""")
EXTENDS_MODIFIER_RE = re.compile(r"""extends\s+([A-Za-z_][A-Za-z0-9_]*)Modifier\b""")
HOOK_CONTENT_MODIFIER_RE = re.compile(r"""\bhook([A-Za-z0-9]+)ContentModifier\b""")
IDL_CONTENT_MODIFIER_RE = re.compile(r"""\b(?:reset)?contentModifier([A-Za-z0-9]+)\b""")
CONTENT_MODIFIER_CUSTOM_RE = re.compile(r"""GetCustomModifier\("contentModifier"\)""")
INCLUDE_PATTERN_COMPONENT_RE = re.compile(r"""pattern/([^/]+)/""")
REASON_SYMBOL_RE = re.compile(r"""\b([A-Z][A-Za-z0-9_]*)\b""")


# ---------------------------------------------------------------------------
# Sentinel / ubiquity sets
# ---------------------------------------------------------------------------
UBIQUITOUS_BASES = {"button", "text", "column", "row", "toggle", "stack", "flex"}
COMMON_PROJECT_HINTS = ("commonattrs", "modifier", "interactiveattributes", "dragcontrol", "focuscontrol")
CONTENT_MODIFIER_NOISE = {
    "accessor", "builder", "commonview", "configuration", "content", "helper",
    "implementation", "modifier", "native",
}
PRIMARY_SCOPE_TIERS = {"direct", "focused"}
SCOPE_TIER_ORDER = {"direct": 0, "focused": 1, "broad": 2}
BUCKET_ORDER = {"must-run": 0, "high-confidence related": 1, "possible related": 2, "excluded": 3}


# ---------------------------------------------------------------------------
# Special path rules (symbol/module mapping for ambiguous paths)
# ---------------------------------------------------------------------------
SPECIAL_PATH_RULES = {
    "componentutils": {
        "modules": ["@ohos.arkui.componentUtils"],
        "symbols": ["componentUtils", "ComponentUtils"],
    },
    "overlaymanager": {
        "modules": ["@ohos.overlayManager", "@ohos.arkui.UIContext"],
        "symbols": ["overlayManager", "OverlayManager", "UIContext"],
    },
    "promptaction": {
        "modules": ["@ohos.promptAction"],
        "symbols": ["promptAction", "AlertDialog", "ActionSheet", "CustomDialog"],
    },
    "ohosprompt": {
        "modules": ["@ohos.prompt"],
        "symbols": ["prompt", "Prompt"],
    },
    "prefetcher": {
        "modules": ["@ohos.arkui.Prefetcher"],
        "symbols": ["BasicPrefetcher", "IPrefetcher", "IDataSourcePrefetching"],
    },
    "shape": {
        "modules": ["@ohos.arkui.shape"],
        "symbols": ["Shape", "RectShape", "CircleShape", "EllipseShape", "PathShape"],
    },
    "matrix4": {
        "modules": ["@ohos.matrix4"],
        "symbols": ["Matrix4"],
    },
    "displaysync": {
        "symbols": ["DisplaySync", "SwiperDynamicSyncScene", "MarqueeDynamicSyncScene"],
    },
    "scrollable": {
        "symbols": ["Scroll", "List", "Grid", "WaterFlow", "Scroller",
                     "ScrollModifier", "ListModifier", "GridModifier", "WaterFlowModifier"],
        "project_hints": ["scroll", "list", "grid", "waterflow"],
    },
    "textfield": {
        "symbols": ["TextInput", "TextArea", "TextInputModifier", "TextAreaModifier"],
        "project_hints": ["textinput", "textarea"],
    },
    "textdrag": {
        "symbols": ["Text", "TextInput", "RichEditor"],
        "project_hints": ["text", "textinput", "richeditor"],
    },
    "scrollbar": {
        "symbols": ["ScrollBar", "Scroll", "Scroller"],
        "project_hints": ["scroll", "scrollbar"],
    },
    "swiperindicator": {
        "symbols": ["Swiper", "SwiperModifier"],
        "project_hints": ["swiper"],
    },
    "selectcontentoverlay": {
        "symbols": ["Select", "SelectModifier"],
        "project_hints": ["select"],
    },
    "selectoverlay": {
        "symbols": ["Select", "SelectModifier"],
        "project_hints": ["select"],
    },
    "formbutton": {
        "symbols": ["FormComponent", "FormLink"],
        "project_hints": ["form"],
    },
}


# ---------------------------------------------------------------------------
# Pattern alias (family → symbol names)
# ---------------------------------------------------------------------------
PATTERN_ALIAS = {
    # --- Already present ---
    "button":       ["Button", "ButtonModifier", "Toggle", "ToggleModifier", "ToggleButton"],
    "toggle":       ["Toggle", "ToggleModifier", "ToggleButton"],
    "text":         ["Text", "Span", "TextModifier", "SpanModifier", "ContainerSpanModifier"],
    "text_input":   ["TextInput", "TextInputModifier"],
    "text_area":    ["TextArea", "TextAreaModifier"],
    "text_clock":   ["TextClock", "TextClockModifier"],
    "text_picker":  ["TextPicker", "TextPickerModifier"],
    "list":         ["List", "ListItem", "ListItemGroup", "ListModifier", "ListItemModifier", "ListItemGroupModifier"],
    "grid":         ["Grid", "GridModifier", "GridItem", "GridItemModifier"],
    "grid_row":     ["GridRow", "GridRowModifier"],
    "grid_col":     ["GridCol", "GridColModifier"],
    "navigation":   ["Navigation", "Navigator", "NavDestination", "NavRouter",
                     "NavigationModifier", "NavDestinationModifier", "NavigatorModifier"],
    "search":       ["Search", "SearchModifier"],
    "swiper":       ["Swiper", "SwiperModifier"],
    "rich_editor":  ["RichEditor", "RichEditorModifier", "SelectionMenu"],
    "dialog":       ["Dialog", "AlertDialog", "ActionSheet", "CustomDialog", "promptAction"],
    "overlay":      ["OverlayManager", "bindOverlay", "bindPopup", "bindSheet"],
    # --- New entries based on SDK arkui/ Modifier declarations ---
    "slider":               ["Slider", "SliderModifier"],
    "image":                ["Image", "ImageModifier", "ImageSpanModifier"],
    "image_animator":       ["ImageAnimator", "ImageAnimatorModifier"],
    "checkbox":             ["Checkbox", "CheckboxModifier"],
    "checkboxgroup":        ["CheckboxGroup", "CheckboxGroupModifier"],
    "radio":                ["Radio", "RadioModifier"],
    "rating":               ["Rating", "RatingModifier"],
    "progress":             ["Progress", "ProgressModifier"],
    "loading_progress":     ["LoadingProgress", "LoadingProgressModifier"],
    "gauge":                ["Gauge", "GaugeModifier"],
    "data_panel":           ["DataPanel", "DataPanelModifier"],
    "marquee":              ["Marquee", "MarqueeModifier"],
    "qrcode":               ["QRCode", "QRCodeModifier"],
    "badge":                ["Badge"],
    "select":               ["Select", "SelectModifier"],
    "video":                ["Video", "VideoModifier"],
    "canvas":               ["Canvas"],
    "tabs":                 ["Tabs", "TabContent", "TabsModifier"],
    "waterflow":            ["WaterFlow", "WaterFlowModifier"],
    "refresh":              ["Refresh", "RefreshModifier"],
    "scroll":               ["Scroll", "ScrollModifier", "Scroller"],
    "indexer":              ["AlphabetIndexer", "AlphabetIndexerModifier"],
    "patternlock":          ["PatternLock", "PatternLockModifier"],
    "picker":               ["DatePicker", "DatePickerModifier"],
    "calendar":             ["Calendar"],
    "calendar_picker":      ["CalendarPicker", "CalendarPickerModifier"],
    "time_picker":          ["TimePicker", "TimePickerModifier"],
    "texttimer":            ["TextTimer", "TextTimerModifier"],
    "counter":              ["Counter", "CounterModifier"],
    "divider":              ["Divider", "DividerModifier"],
    "blank":                ["Blank", "BlankModifier"],
    "hyperlink":            ["Hyperlink", "HyperlinkModifier"],
    "side_bar":             ["SideBarContainer", "SideBarContainerModifier"],
    "linear_layout":        ["Column", "Row", "ColumnModifier", "RowModifier"],
    "flex":                 ["Flex", "FlexModifier"],
    "stack":                ["Stack", "StackModifier"],
    "linear_split":         ["ColumnSplit", "RowSplit", "ColumnSplitModifier", "RowSplitModifier"],
    "stepper":              ["Stepper", "StepperItem", "StepperModifier", "StepperItemModifier"],
    "panel":                ["Panel", "PanelModifier"],
    "particle":             ["Particle", "ParticleModifier"],
    "menu":                 ["Menu", "MenuItem", "MenuItemGroup", "MenuModifier", "MenuItemModifier"],
    "relative_container":   ["RelativeContainer"],
    # --- NEW ENTRIES: HIGH priority (SDK declarations + XTS tests) ---
    "gesture":              ["GestureGroup", "TapGesture", "LongPressGesture",
                             "PanGesture", "PinchGesture", "RotationGesture", "SwipeGesture"],
    "xcomponent":           ["XComponent", "XComponentController"],
    "web":                  ["Web", "WebviewController"],
    "form":                 ["FormComponent", "FormLink"],
    "folder_stack":         ["FolderStack"],
    "animator":             ["Animator"],
    "scroll_bar":           ["ScrollBar"],
    "toast":                ["promptAction"],
    "sheet":                ["bindSheet", "SheetSize"],
    "action_sheet":         ["ActionSheet"],
    "bubble":               ["Popup", "bindPopup"],
    "symbol":               ["SymbolGlyph", "SymbolSpan", "SymbolSpanModifier"],
    "security_component":   ["LocationButton", "PasteButton", "SaveButton"],
    "navrouter":            ["NavRouter", "NavDestination"],
    "navigator":            ["Navigator"],
    "toolbaritem":          ["ToolBar", "ToolBarItem"],
    # --- NEW ENTRIES: MEDIUM priority (internal, but XTS-linked) ---
    "text_field":           ["TextInput", "TextArea", "TextInputModifier", "TextAreaModifier"],
    "scrollable":           ["Scroll", "List", "Grid", "WaterFlow"],
    "node_container":       ["NodeContainer"],
    "effect_component":     ["EffectComponent"],
    "form_link":            ["FormLink"],
    "grid_container":       ["GridContainer"],
    "swiper_indicator":     ["Swiper", "SwiperModifier"],
    "render_node":          ["RenderNode", "FrameNode", "BuilderNode"],
}


# ---------------------------------------------------------------------------
# Default composite mappings
# ---------------------------------------------------------------------------
DEFAULT_COMPOSITE_MAPPINGS = {
    "content_modifier_helper_accessor": {
        "families": [
            "button", "checkbox", "checkboxgroup", "datapanel", "gauge",
            "loadingprogress", "menuitem", "progress", "radio", "rating",
            "select", "slider", "textclock", "texttimer", "toggle",
        ],
        "project_hints": ["contentmodifier"],
        "method_hints": ["contentModifier"],
        "type_hints": ["ContentModifier"],
        "symbols": ["ContentModifier"],
        "method_hint_required": True,
    },
    "common_method_modifier": {
        "project_hints": list(COMMON_PROJECT_HINTS),
        "symbols": ["CommonModifier", "ModifierUtils"],
    },
    "common_view_model_ng": {
        "project_hints": ["commonattrs"],
        "symbols": ["CommonModifier", "ModifierUtils"],
    },
}


# ---------------------------------------------------------------------------
# File / path constants
# ---------------------------------------------------------------------------
DEFAULT_REPORT_FILE = "arkui_xts_selector_report.json"
SELECTED_TESTS_FILE_NAME = "selected_tests.json"
