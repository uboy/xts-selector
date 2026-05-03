@Entry
@Component
struct NavigationTest {
  build() {
    Navigation() {
      Text('Content')
    }
    .title('My Nav')
    .mode(NavigationMode.Stack)
    .navBarWidth('200vp')
  }
}
