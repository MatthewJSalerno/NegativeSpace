import { MenuButton } from "./ui/MenuButton";
import { count } from "../format";

// Selecting in bulk (webui-spec 2): the photos on screen, or everything the view shows,
// and the same two to unselect; the on-screen pair only when the view holds more than the
// screen shows. An item that would do nothing, or cannot, says why.
export function SelectMenu({ onScreen, screenSelected, total, selected, max, disabledWhy, onSelectScreen, onSelectAll,
                             onUnselectScreen, onUnselectAll }: {
  onScreen: number;
  screenSelected: number;
  total: number;
  selected: number;
  max: number;
  disabledWhy: string | null;
  onSelectScreen: () => void;
  onSelectAll: () => void;
  onUnselectScreen: () => void;
  onUnselectAll: () => void;
}) {
  // With every photo of the view on screen, "on screen" would repeat "in this view": offered
  // only when the view holds more than the screen shows.
  const partial = onScreen < total;
  const items = [
    ...(partial ? [{ label: `Select all on screen (${count(onScreen)})`, onClick: onSelectScreen,
      why: disabledWhy ?? (screenSelected === onScreen ? "Every photo on screen is selected." : null),
      hint: "The photos you can see right now." }] : []),
    { label: `Select all in this view (${count(total)})`, onClick: onSelectAll,
      why: disabledWhy ?? (total > max
        ? `More than the ${count(max)}-photo limit. Use Actions for all photos, or narrow the view.` : null),
      hint: "Every photo the view, search and dates show, scrolled to or not." },
    ...(partial ? [{ label: "Unselect all on screen", onClick: onUnselectScreen,
      why: disabledWhy ?? (screenSelected === 0 ? "Nothing on screen is selected." : null) }] : []),
    { label: "Unselect all", onClick: onUnselectAll, why: selected === 0 ? "Nothing is selected." : null },
  ];

  return <MenuButton label="Select" items={items} className="select-menu" />;
}
