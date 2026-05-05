declare class MenuItemAttribute extends CommonMethod<MenuItemAttribute> {
  content(value: ResourceStr): MenuItemAttribute;
  selected(value: boolean): MenuItemAttribute;
  onSelect(callback: () => void): MenuItemAttribute;
  contentModifier(modifier: ContentModifier<MenuItemConfiguration>): MenuItemAttribute;
}

interface MenuItemInterface {
  (value?: ResourceStr, icon?: ResourceStr): MenuItemAttribute;
}

declare const MenuItem: MenuItemInterface;
