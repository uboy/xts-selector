declare class SliderAttribute extends CommonMethod<SliderAttribute> {
  value(value: number): SliderAttribute;
  min(value: number): SliderAttribute;
  max(value: number): SliderAttribute;
  step(value: number): SliderAttribute;
  style(value: SliderStyle): SliderAttribute;
  blockColor(value: ResourceColor): SliderAttribute;
}

interface SliderInterface {
  (value?: number, min?: number, max?: number): SliderAttribute;
}

declare const Slider: SliderInterface;
