declare class ButtonAttribute extends CommonMethod<ButtonAttribute> {
  type(value: ButtonType): ButtonAttribute;
  buttonStyle(value: ButtonStyleMode): ButtonAttribute;
  controlSize(value: ControlSize): ButtonAttribute;
  role(value: ButtonRole): ButtonAttribute;
  contentModifier(modifier: ContentModifier<ButtonConfiguration>): ButtonAttribute;
  onClick(event: (event: ClickEvent) => void): ButtonAttribute;
}

declare class ButtonModifier implements AttributeModifier<ButtonAttribute> {
  applyNormalAttribute(instance: ButtonAttribute): void;
  applyPressedAttribute?(instance: ButtonAttribute): void;
}

interface ButtonInterface {
  (): ButtonAttribute;
  (options: ButtonOptions): ButtonAttribute;
}

declare const Button: ButtonInterface;
