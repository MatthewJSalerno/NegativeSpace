import { MenuButton, type MenuEntry } from "./ui/MenuButton";
import { count } from "../format";

type Mode = "copy" | "move";

// Why an item cannot run, or null when it can. Every disabled item says why.
export interface ActionState {
  jobRunning: boolean;
  noPhotos: boolean;
  selected: number;
  tooMany: boolean;
  maxSelection: number;
  eligible: Record<Mode, number>;
  copied: number;
  // The Folders tree's one folder shown, with what a Copy or Move of it would take;
  // `folders` is how many are ticked, to say why "this folder" waits for exactly one.
  // Absent on pages without the tree.
  folder?: { name: string; eligible: Record<Mode, number> } | null;
  folders?: number;
}

// The Actions menu (webui-spec 4): Index, and Copy and Move each for the photos
// selected in the Library, for the one folder the Folders tree shows (no 1,000 limit:
// the engine takes the folder, not a list of photos), or for every photo the engine
// would take. The counts are the whole catalog's (GET /status) or the folder's, never
// the gallery's current view or search.
export function ActionsMenu({ state, onIndex, onTransfer }: {
  state: ActionState;
  onIndex: () => void;
  onTransfer: (mode: Mode, scope: "selected" | "folder" | "all") => void;
}) {
  const busy = state.jobRunning ? "A job is running. Wait for it to finish or cancel it." : null;
  const empty = state.noPhotos ? "Index your library first - NegativeSpace acts on indexed photos." : null;
  const indexWhy = busy;
  const selectedWhy = busy ?? empty
    ?? (state.selected === 0 ? "Select photos in the Library first."
      : state.tooMany ? `${count(state.maxSelection)} file limit for individual selection.` : null);
  const allWhy = (mode: Mode) => busy ?? empty
    ?? (state.eligible[mode] === 0
      ? (mode === "copy" ? "Nothing to copy - every photo is copied or organized." : "Nothing to move - every photo is organized.")
      : null);

  const folderWhy = (mode: Mode) => busy ?? empty
    ?? (state.folder == null
      ? ((state.folders ?? 0) > 1 ? "Show one folder to act on it." : "Show a folder in the Folders tree to act on it.")
      : state.folder.eligible[mode] === 0
        ? (mode === "copy" ? "Nothing to copy there - every photo in it is copied or organized." : "Nothing to move there - every photo in it is organized.")
        : null);
  const allHint = (mode: Mode) => mode === "copy"
    ? "Every photo not yet copied. The source is left untouched."
    : state.copied > 0
      ? `Every photo not yet moved, including ${count(state.copied)} already copied: each source is deleted once its copy is verified again.`
      : "Every photo not yet organized. Each source is deleted only after its copy is verified.";

  const verb = (mode: Mode) => (mode === "copy" ? "Copy" : "Move");

  const items: MenuEntry[] = [
    { label: "Index", hint: "Read new and changed photos from the source. Nothing is moved or copied.", why: indexWhy, onClick: onIndex },
    ...(["copy", "move"] as Mode[]).map((mode) => ({
      label: verb(mode), children: [
        { label: `${verb(mode)} selected (${count(state.selected)})`, hint: "The photos selected in the Library.",
          why: selectedWhy, onClick: () => onTransfer(mode, "selected") },
        ...(state.folders === undefined ? [] : [{
          label: state.folder ? `${verb(mode)} this folder: ${state.folder.name} (${count(state.folder.eligible[mode])})` : `${verb(mode)} this folder`,
          hint: "Everything in it and its subfolders, however many: no 1,000 limit.", why: folderWhy(mode),
          onClick: () => onTransfer(mode, "folder"),
        }]),
        { label: `${verb(mode)} all (${count(state.eligible[mode])})`, hint: allHint(mode), why: allWhy(mode),
          onClick: () => onTransfer(mode, "all") },
      ],
    })),
  ];
  return <MenuButton label="Actions" items={items} />;
}
