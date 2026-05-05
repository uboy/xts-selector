@Entry
@Component
struct SliderTest {
  build() {
    Column() {
      Slider({ value: 50, min: 0, max: 100 })
        .step(10)
        .style(SliderStyle.OutSet)
        .blockColor(Color.Red)
    }
  }
}
