// Fixture: Text component with attribute-only usage (no following attribute → medium confidence)
@Entry
@Component
struct TextPage {
  build() {
    Column() {
      Text("hello world")

      Text("styled")
        .fontSize(20)
        .fontColor(0xCCCCCC)
        .lineHeight(25)
        .textAlign(TextAlign.Center)
        .textOverflow({ overflow: TextOverflow.None })
    }
  }
}
