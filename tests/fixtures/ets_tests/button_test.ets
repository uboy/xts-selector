@Entry
@Component
struct ButtonTest {
  build() {
    Column() {
      Button('Click me')
        .type(ButtonType.Capsule)
        .buttonStyle(ButtonStyleMode.NORMAL)
        .role(ButtonRole.NORMAL)
        .onClick(() => {
          console.info('clicked')
        })

      Button({ type: ButtonType.Normal })
        .controlSize({ width: 100, height: 50 })
        .contentModifier(new ButtonModifierExample())
    }
  }
}

class ButtonModifierExample implements ContentModifier<ButtonConfiguration> {
  applyNormalAttribute(instance: ButtonAttribute): void {
    instance.type(ButtonType.Capsule)
  }
}
