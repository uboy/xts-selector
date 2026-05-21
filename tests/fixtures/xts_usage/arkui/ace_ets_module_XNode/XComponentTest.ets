import { XComponentController } from '@ohos.arkui.component';

@Entry
@Component
struct XComponentTest {
  controller: XComponentController = new XComponentController();
  build() {
    XComponent({ id: 'test', type: XComponentType.SURFACE, controller: this.controller })
  }
}
