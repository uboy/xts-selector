// Fixture: Event handler usage patterns
@Entry
@Component
struct EventPage {
  build() {
    Column() {
      TextInput({ placeholder: 'type here' })
        .onChange((value: string) => {
          console.info('changed: ' + value)
        })
        .onFocus(() => {
          console.info('focused')
        })
        .onBlur(() => {
          console.info('blurred')
        })
        .onSubmit((enterKey: EnterKeyType) => {
          console.info('submitted')
        })
    }
  }
}
