import { PanGesture, PanGestureOptions } from '@ohos.arkui.gesture';

@Entry
@Component
struct PanGestureTest {
  build() {
    Column()
      .gesture(PanGesture({fingers: 1}))
  }
}
