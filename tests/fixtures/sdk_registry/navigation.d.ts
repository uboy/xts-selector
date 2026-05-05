declare class NavigationAttribute extends CommonMethod<NavigationAttribute> {
  title(value: string): NavigationAttribute;
  subtitle(value: string): NavigationAttribute;
  mode(value: NavigationMode): NavigationAttribute;
  navDestination(builder: NavDestinationBuilder): NavigationAttribute;
  navBarWidth(value: Length): NavigationAttribute;
}

interface NavigationInterface {
  (): NavigationAttribute;
}

declare const Navigation: NavigationInterface;
