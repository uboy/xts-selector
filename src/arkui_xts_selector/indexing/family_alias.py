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
    "canvas": "Canvas",
    "checkbox": "Checkbox",
    "clock": "Clock",
    "column_split": "ColumnSplit",
    "counter": "Counter",
    "data_panel": "DataPanel",
    "divider": "Divider",
    "flex": "Flex",
    "flow_item": "FlowItem",
    "form": "Form",
    "gauge": "Gauge",
    "grid_col": "GridCol",
    "grid_row": "GridRow",
    "grid": "Grid",
    "hyperlink": "Hyperlink",
    "image": "Image",
    "image_animator": "ImageAnimator",
    "list": "List",
    "list_item": "ListItem",
    "marquee": "Marquee",
    "menu": "Menu",
    "navigation": "Navigation",
    "nav_router": "NavRouter",
    "panel": "Panel",
    "picker": "Picker",
    "progress": "Progress",
    "qrcode": "QRCode",
    "radio": "Radio",
    "rating": "Rating",
    "refresh": "Refresh",
    "row_split": "RowSplit",
    "scroll": "Scroll",
    "search": "Search",
    "select": "Select",
    "slider": "Slider",
    "span": "Span",
    "stack": "Stack",
    "stepper": "Stepper",
    "swiper": "Swiper",
    "tab_content": "TabContent",
    "tabs": "Tabs",
    "text": "Text",
    "text_area": "TextArea",
    "text_input": "TextInput",
    "text_timer": "TextTimer",
    "toggle": "Toggle",
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
            aliases = {**aliases, **data.get("aliases", {})}  # config overrides defaults
        except (json.JSONDecodeError, OSError):
            pass

    key = snake_name.lower().strip()
    if key in aliases:
        return aliases[key]

    # Fallback: snake_case → PascalCase
    return "".join(part.capitalize() for part in key.split("_"))
