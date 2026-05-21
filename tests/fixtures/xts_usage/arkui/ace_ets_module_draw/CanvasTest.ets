import { CanvasRenderingContext2D } from '@ohos.arkui.component';

@Entry
@Component
struct CanvasTest {
  private ctx: CanvasRenderingContext2D = new CanvasRenderingContext2D();
  build() {
    Canvas(this.ctx).width(300).height(300)
  }
}
