// Fixture: Slider component with attribute and enum usage
@Entry
@Component
struct SliderPage {
  build() {
    Column() {
      Slider({ value: 50, min: 0, max: 100 })
        .step(10)
        .style(SliderStyle.OutSet)
        .blockColor(Color.Red)
        .onChange((value: number, mode: SliderChangeMode) => {
          console.info('slider value: ' + value)
        })
    }
  }
}
