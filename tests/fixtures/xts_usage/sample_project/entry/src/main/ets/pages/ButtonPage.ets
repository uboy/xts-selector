// Fixture: Button component_creation with attribute chain and enum usage
@Entry
@Component
struct ButtonPage {
  build() {
    Column() {
      Button('Click me')
        .type(ButtonType.Capsule)
        .fontSize(16)
        .fontColor(Color.White)
        .onClick(() => {
          console.info('button clicked')
        })

      Button({ type: ButtonType.Normal })
        .buttonStyle(ButtonStyleMode.NORMAL)
        .role(ButtonRole.NORMAL)
    }
  }
}
