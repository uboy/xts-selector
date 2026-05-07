# Session 4.1 — Canonical accuracy diagnostic

## Oracle coverage

- PRs with oracle data: 25/30
- Total high_confidence method changes: 62
- Total medium_confidence: 466
- Total unmapped (no SDK match): 68

## Selector vs oracle on 12 covered PRs

| PR | oracle_high | oracle_med | selector_canonical | selector_apis |
|---|---:|---:|---:|---:|
| #81536 | 0 | 0 | 0 | 0 |
| #81882 | 34 | 200 | 8 | 11 |
| #82131 | 0 | 6 | 0 | 0 |
| #82604 | 0 | 44 | 0 | 0 |
| #82620 | 2 | 0 | 0 | 0 |
| #82928 | 10 | 38 | 0 | 1 |
| #83100 | 0 | 0 | 0 | 0 |
| #83256 | 0 | 0 | 0 | 0 |
| #83403 | 0 | 0 | 0 | 0 |
| #83580 | 0 | 0 | 0 | 0 |
| #83761 | 0 | 4 | 0 | 0 |
| #83822 | 0 | 0 | 0 | 0 |
| #83851 | 0 | 0 | 181 | 211 |
| #83913 | 0 | 0 | 0 | 0 |
| #83970 | 0 | 0 | 0 | 0 |
| #83998 | 0 | 0 | 0 | 1 |
| #84055 | 8 | 174 | 0 | 0 |
| #84069 | 0 | 0 | 0 | 0 |
| #84097 | 8 | 0 | 0 | 0 |
| #84113 | 0 | 0 | 0 | 0 |
| #84156 | 0 | 0 | 0 | 0 |
| #84168 | 0 | 0 | 0 | 0 |
| #84255 | 0 | 0 | 0 | 0 |
| #84268 | 0 | 0 | 0 | 0 |
| #84301 | 0 | 0 | 0 | 0 |

## Why high-confidence APIs are missed by selector

For each oracle high_confidence entry, check if selector found a matching canonical.

High-confidence matched: 2/62
High-confidence missed: 60/62

### Top 30 missed high_confidence:

| PR | Oracle method (family/Method) | Selector found canonical IDs |
|---|---|---|
| #81882 | `text/SetOnWillCopy` | ['api:v1:arkui.static:event_or_method:common#OffscreenCanvasRenderingContext2D%23clip', 'api:v1:arkui.static:event_or_method:@internal#TextAttribute%23draggable', 'api:v1:arkui.static:event_or_method:@internal#CommonMethod%23focusable'] |
| #81882 | `text/SetStyledString` | ['api:v1:arkui.static:event_or_method:common#OffscreenCanvasRenderingContext2D%23clip', 'api:v1:arkui.static:event_or_method:@internal#TextAttribute%23draggable', 'api:v1:arkui.static:event_or_method:@internal#CommonMethod%23focusable'] |
| #81882 | `text/SetFontVariations` | ['api:v1:arkui.static:event_or_method:common#OffscreenCanvasRenderingContext2D%23clip', 'api:v1:arkui.static:event_or_method:@internal#TextAttribute%23draggable', 'api:v1:arkui.static:event_or_method:@internal#CommonMethod%23focusable'] |
| #81882 | `text/ResetFontVariations` | ['api:v1:arkui.static:event_or_method:common#OffscreenCanvasRenderingContext2D%23clip', 'api:v1:arkui.static:event_or_method:@internal#TextAttribute%23draggable', 'api:v1:arkui.static:event_or_method:@internal#CommonMethod%23focusable'] |
| #81882 | `text/GetFontVariations` | ['api:v1:arkui.static:event_or_method:common#OffscreenCanvasRenderingContext2D%23clip', 'api:v1:arkui.static:event_or_method:@internal#TextAttribute%23draggable', 'api:v1:arkui.static:event_or_method:@internal#CommonMethod%23focusable'] |
| #81882 | `text/SetOnWillCopy` | ['api:v1:arkui.static:event_or_method:common#OffscreenCanvasRenderingContext2D%23clip', 'api:v1:arkui.static:event_or_method:@internal#TextAttribute%23draggable', 'api:v1:arkui.static:event_or_method:@internal#CommonMethod%23focusable'] |
| #81882 | `text/SetStyledString` | ['api:v1:arkui.static:event_or_method:common#OffscreenCanvasRenderingContext2D%23clip', 'api:v1:arkui.static:event_or_method:@internal#TextAttribute%23draggable', 'api:v1:arkui.static:event_or_method:@internal#CommonMethod%23focusable'] |
| #81882 | `text/SetFontVariations` | ['api:v1:arkui.static:event_or_method:common#OffscreenCanvasRenderingContext2D%23clip', 'api:v1:arkui.static:event_or_method:@internal#TextAttribute%23draggable', 'api:v1:arkui.static:event_or_method:@internal#CommonMethod%23focusable'] |
| #81882 | `text/ResetFontVariations` | ['api:v1:arkui.static:event_or_method:common#OffscreenCanvasRenderingContext2D%23clip', 'api:v1:arkui.static:event_or_method:@internal#TextAttribute%23draggable', 'api:v1:arkui.static:event_or_method:@internal#CommonMethod%23focusable'] |
| #81882 | `text/GetFontVariations` | ['api:v1:arkui.static:event_or_method:common#OffscreenCanvasRenderingContext2D%23clip', 'api:v1:arkui.static:event_or_method:@internal#TextAttribute%23draggable', 'api:v1:arkui.static:event_or_method:@internal#CommonMethod%23focusable'] |
| #81882 | `text/SetFontVariations` | ['api:v1:arkui.static:event_or_method:common#OffscreenCanvasRenderingContext2D%23clip', 'api:v1:arkui.static:event_or_method:@internal#TextAttribute%23draggable', 'api:v1:arkui.static:event_or_method:@internal#CommonMethod%23focusable'] |
| #81882 | `text/GetFontVariations` | ['api:v1:arkui.static:event_or_method:common#OffscreenCanvasRenderingContext2D%23clip', 'api:v1:arkui.static:event_or_method:@internal#TextAttribute%23draggable', 'api:v1:arkui.static:event_or_method:@internal#CommonMethod%23focusable'] |
| #81882 | `text/SetOnWillCopy` | ['api:v1:arkui.static:event_or_method:common#OffscreenCanvasRenderingContext2D%23clip', 'api:v1:arkui.static:event_or_method:@internal#TextAttribute%23draggable', 'api:v1:arkui.static:event_or_method:@internal#CommonMethod%23focusable'] |
| #81882 | `text/SetStyledString` | ['api:v1:arkui.static:event_or_method:common#OffscreenCanvasRenderingContext2D%23clip', 'api:v1:arkui.static:event_or_method:@internal#TextAttribute%23draggable', 'api:v1:arkui.static:event_or_method:@internal#CommonMethod%23focusable'] |
| #81882 | `text/ResetFontVariations` | ['api:v1:arkui.static:event_or_method:common#OffscreenCanvasRenderingContext2D%23clip', 'api:v1:arkui.static:event_or_method:@internal#TextAttribute%23draggable', 'api:v1:arkui.static:event_or_method:@internal#CommonMethod%23focusable'] |
| #81882 | `text/unknown` | ['api:v1:arkui.static:event_or_method:common#OffscreenCanvasRenderingContext2D%23clip', 'api:v1:arkui.static:event_or_method:@internal#TextAttribute%23draggable', 'api:v1:arkui.static:event_or_method:@internal#CommonMethod%23focusable'] |
| #81882 | `text/SetFontVariations` | ['api:v1:arkui.static:event_or_method:common#OffscreenCanvasRenderingContext2D%23clip', 'api:v1:arkui.static:event_or_method:@internal#TextAttribute%23draggable', 'api:v1:arkui.static:event_or_method:@internal#CommonMethod%23focusable'] |
| #81882 | `text/GetFontVariations` | ['api:v1:arkui.static:event_or_method:common#OffscreenCanvasRenderingContext2D%23clip', 'api:v1:arkui.static:event_or_method:@internal#TextAttribute%23draggable', 'api:v1:arkui.static:event_or_method:@internal#CommonMethod%23focusable'] |
| #81882 | `text/SetOnWillCopy` | ['api:v1:arkui.static:event_or_method:common#OffscreenCanvasRenderingContext2D%23clip', 'api:v1:arkui.static:event_or_method:@internal#TextAttribute%23draggable', 'api:v1:arkui.static:event_or_method:@internal#CommonMethod%23focusable'] |
| #81882 | `text/SetStyledString` | ['api:v1:arkui.static:event_or_method:common#OffscreenCanvasRenderingContext2D%23clip', 'api:v1:arkui.static:event_or_method:@internal#TextAttribute%23draggable', 'api:v1:arkui.static:event_or_method:@internal#CommonMethod%23focusable'] |
| #81882 | `text/ResetFontVariations` | ['api:v1:arkui.static:event_or_method:common#OffscreenCanvasRenderingContext2D%23clip', 'api:v1:arkui.static:event_or_method:@internal#TextAttribute%23draggable', 'api:v1:arkui.static:event_or_method:@internal#CommonMethod%23focusable'] |
| #81882 | `text/unknown` | ['api:v1:arkui.static:event_or_method:common#OffscreenCanvasRenderingContext2D%23clip', 'api:v1:arkui.static:event_or_method:@internal#TextAttribute%23draggable', 'api:v1:arkui.static:event_or_method:@internal#CommonMethod%23focusable'] |
| #81882 | `text/SetFontVariations` | ['api:v1:arkui.static:event_or_method:common#OffscreenCanvasRenderingContext2D%23clip', 'api:v1:arkui.static:event_or_method:@internal#TextAttribute%23draggable', 'api:v1:arkui.static:event_or_method:@internal#CommonMethod%23focusable'] |
| #81882 | `text/SetFontVariations` | ['api:v1:arkui.static:event_or_method:common#OffscreenCanvasRenderingContext2D%23clip', 'api:v1:arkui.static:event_or_method:@internal#TextAttribute%23draggable', 'api:v1:arkui.static:event_or_method:@internal#CommonMethod%23focusable'] |
| #81882 | `text/SetFontVariations` | ['api:v1:arkui.static:event_or_method:common#OffscreenCanvasRenderingContext2D%23clip', 'api:v1:arkui.static:event_or_method:@internal#TextAttribute%23draggable', 'api:v1:arkui.static:event_or_method:@internal#CommonMethod%23focusable'] |
| #81882 | `text/ResetFontVariations` | ['api:v1:arkui.static:event_or_method:common#OffscreenCanvasRenderingContext2D%23clip', 'api:v1:arkui.static:event_or_method:@internal#TextAttribute%23draggable', 'api:v1:arkui.static:event_or_method:@internal#CommonMethod%23focusable'] |
| #81882 | `text/unknown` | ['api:v1:arkui.static:event_or_method:common#OffscreenCanvasRenderingContext2D%23clip', 'api:v1:arkui.static:event_or_method:@internal#TextAttribute%23draggable', 'api:v1:arkui.static:event_or_method:@internal#CommonMethod%23focusable'] |
| #81882 | `text/SetFontVariations` | ['api:v1:arkui.static:event_or_method:common#OffscreenCanvasRenderingContext2D%23clip', 'api:v1:arkui.static:event_or_method:@internal#TextAttribute%23draggable', 'api:v1:arkui.static:event_or_method:@internal#CommonMethod%23focusable'] |
| #81882 | `text/ResetFontVariations` | ['api:v1:arkui.static:event_or_method:common#OffscreenCanvasRenderingContext2D%23clip', 'api:v1:arkui.static:event_or_method:@internal#TextAttribute%23draggable', 'api:v1:arkui.static:event_or_method:@internal#CommonMethod%23focusable'] |
| #81882 | `text/unknown` | ['api:v1:arkui.static:event_or_method:common#OffscreenCanvasRenderingContext2D%23clip', 'api:v1:arkui.static:event_or_method:@internal#TextAttribute%23draggable', 'api:v1:arkui.static:event_or_method:@internal#CommonMethod%23focusable'] |

## Pattern analysis of missed high_confidence

### Top 10 families with missed methods:
  text: 34
  rich_editor: 16
  navigation: 6
  button: 2
  navrouter: 2

### Top 15 method names missed:
  SetFontVariations: 8
  ResetFontVariations: 6
  ScrollToVisible: 6
  SetOnWillCopy: 4
  SetStyledString: 4
  GetFontVariations: 4
  unknown: 4
  SetTitleHeight: 4
  SetFontVariationsImpl: 2
  SetOnWillCopyImpl: 2
  SetTextDefaultStyle: 2
  UpdateDividerEndMargin: 2
  UpdateDividerStartMargin: 2
  SetMaxLines: 2
  RichEditorModel: 2

## Oracle unmapped (SDK lookup failed in oracle itself)
Total: 68

### Top 20 unmapped method names:
  view_abstract/JsInspectorLabel: 6
  text/SetFontVariations: 4
  text/SetOnWillCopy: 4
  text/CreateSimpleJsOnWillObj: 4
  view_abstract/JSBind: 4
  text/ParseJsFontVariations: 2
  text/SetFontWeight: 2
  text/SetTextContentAlign: 2
  text/JSBind: 2
  text/ParseFontWeightInfo: 2
  text/RegisterColorResource: 2
  navigation_stack/ExecutePopCallbackForHomeNavDestination: 2
  node_common/ResetInspectorLabel: 2
  node_common/SetInspectorLabel: 2
  node_common/GetInspectorLabel: 2
  node_common/ResetPointLightBloom: 2
  node_common/SetHistoryTouchEvent: 2
  node_common/unknown: 2
  node_common/CheckBackShadowResObj: 2
  view_abstract/JSUseUnion: 2
