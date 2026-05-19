// Fixture: Ambiguous standalone method calls — should NOT produce modifier-name api entries
// This simulates what you'd see with internal C++ bridge patterns that are NOT SDK-visible.

// This function call is ambiguous — no PascalCase component context
function applyStyle(btn: ButtonAttribute): void {
  btn.fontSize(16)
  btn.fontColor(Color.Blue)
}

// A plain TypeScript function that looks like an attribute call but has no component context
function setupSlider(s: SliderAttribute): void {
  s.step(5)
}
