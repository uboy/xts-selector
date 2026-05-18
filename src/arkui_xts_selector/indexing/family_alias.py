"""Family name normalization: snake_case ACE paths → PascalCase SDK names."""

from __future__ import annotations

import json
from pathlib import Path

_DEFAULT_ALIASES = {
    "alert_dialog": "AlertDialog",
    "badge": "Badge",
    "blank": "Blank",
    "button": "Button",
    "calendar": "Calendar",
    "calendar_picker": "CalendarPicker",
    "canvas": "Canvas",
    "checkbox": "Checkbox",
    "checkbox_group": "CheckboxGroup",
    "clock": "Clock",
    "column_split": "ColumnSplit",
    "counter": "Counter",
    "data_panel": "DataPanel",
    "date_picker": "DatePicker",
    "divider": "Divider",
    "flex": "Flex",
    "flow_item": "FlowItem",
    "folder_stack": "FolderStack",
    "form": "Form",
    "gauge": "Gauge",
    "grid_col": "GridCol",
    "grid_row": "GridRow",
    "grid": "Grid",
    "hyperlink": "Hyperlink",
    "image": "Image",
    "image_animator": "ImageAnimator",
    "loading_progress": "LoadingProgress",
    "list": "List",
    "list_item": "ListItem",
    "marquee": "Marquee",
    "menu": "Menu",
    "menu_item": "MenuItem",
    "nav_destination": "NavDestination",
    "navdestination": "NavDestination",
    "navigation": "Navigation",
    "nav_router": "NavRouter",
    "panel": "Panel",
    "pattern_lock": "PatternLock",
    "picker": "Picker",
    "progress": "Progress",
    "qrcode": "QRCode",
    "radio": "Radio",
    "rating": "Rating",
    "refresh": "Refresh",
    "relative_container": "RelativeContainer",
    "rich_editor": "RichEditor",
    "row_split": "RowSplit",
    "scroll": "Scroll",
    "scroll_bar": "ScrollBar",
    "search": "Search",
    "security_component": "SecurityComponent",
    "select": "Select",
    "side_bar": "SideBarContainer",
    "slider": "Slider",
    "span": "Span",
    "stack": "Stack",
    "stepper": "Stepper",
    "swiper": "Swiper",
    "symbol_glyph": "SymbolGlyph",
    "tab_content": "TabContent",
    "tabs": "Tabs",
    "text": "Text",
    "text_area": "TextArea",
    "text_field": "TextInput",
    "text_input": "TextInput",
    "text_picker": "TextPicker",
    "text_timer": "TextTimer",
    "time_picker": "TimePicker",
    "toggle": "Toggle",
    "tool_bar": "ToolBar",
    "video": "Video",
    "web": "Web",
    "water_flow": "WaterFlow",
    "xcomponent": "XComponent",
}


def normalize_family(snake_name: str, config_path: Path | None = None) -> str:
    """Convert snake_case family name to PascalCase SDK name.

    Args:
        snake_name: Snake case family name (e.g., "button", "alert_dialog")
        config_path: Optional path to family_aliases.json for custom mappings

    Returns:
        PascalCase SDK name (e.g., "Button", "AlertDialog")
    """
    aliases = _DEFAULT_ALIASES
    if config_path and config_path.exists():
        try:
            data = json.loads(config_path.read_text(encoding="utf-8"))
            aliases = {
                **aliases,
                **data.get("aliases", {}),
            }  # config overrides defaults
        except (json.JSONDecodeError, OSError):
            pass

    key = snake_name.lower().strip()
    if key in aliases:
        return aliases[key]

    # Fallback: snake_case → PascalCase
    return "".join(part.capitalize() for part in key.split("_"))
