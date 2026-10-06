import { MenuButton, type MenuEntry } from "./ui/MenuButton";
import type { ActionMode } from "../api";
import { count } from "../format";

type Mode = "copy" | "move";

// Why an item cannot run, or null when it can. Every disabled item says why.
export interface ActionState {
  jobRunning: boolean;
  noPhotos: boolean;
  selected: number;
  eligible: Record<Mode, number>;
  copied: number;
  // The Folders tree's one folder shown, with what a Copy or Move of it would take;
  // `folders` is how many are ticked, to say why "this folder" waits for exactly one.
  // Absent on pages without the tree.
  folder?: { name: string; eligible: Record<Mode, number> } | null;
  folders?: number;
  // On the Library page: what Reject and Return to library would take of the selection,
  // and whether the Rejects view is shown (Return there, Reject everywhere else).
  rejects?: { reject: number; return: number; inRejectsView: boolean } | null;
}

// The Actions menu (webui-spec 4): Index, and Copy and Move each for the photos
// selected in the Library, for the one folder the Folders tree shows, or for every photo
// the engine would take. Reject and Return to library act on a selection or a folder only, never
// on everything. The counts are the whole catalog's (GET /status) or the folder's,
// never the gallery's current view or search.
export function ActionsMenu({ state, onIndex, onTransfer }: {
  state: ActionState;
  onIndex: () => void;
  onTransfer: (mode: ActionMode, scope: "selected" | "folder" | "all") => void;
}) {
  const busy = state.jobRunning ? "A job is running. Wait for it to finish or cancel it." : null;
  const empty = state.noPhotos ? "Index your library first - NegativeSpace acts on indexed photos." : null;
  const indexWhy = busy;
  const selectedWhy = busy ?? empty
    ?? (state.selected === 0 ? "Select photos in the Library first." : null);
  const allWhy = (mode: Mode) => busy ?? empty
    ?? (state.eligible[mode] === 0
      ? (mode === "copy" ? "Nothing to copy - every photo is copied or organized." : "Nothing to move - every photo is organized.")
      : null);

  const nothingThere: Record<Mode, string> = {
    copy: "Nothing to copy there - every photo in it is copied or organized.",
    move: "Nothing to move there - every photo in it is organized.",
  };
  const folderWhy = (mode: Mode) => busy ?? empty
    ?? (state.folder == null
      ? ((state.folders ?? 0) > 1 ? "Show one folder to act on it." : "Show a folder in the Folders tree to act on it.")
      : state.folder.eligible[mode] === 0 ? nothingThere[mode] : null);
  const allHint = (mode: Mode) => mode === "copy"
    ? "Every photo not yet copied. The source is left untouched."
    : state.copied > 0
      ? `Every photo not yet moved, including ${count(state.copied)} already copied: each source is deleted once its copy is verified again.`
      : "Every photo not yet organized. Each source is deleted only after its copy is verified.";

  const verb = (mode: Mode) => (mode === "copy" ? "Copy" : "Move");
  const folderItem = (mode: Mode, hint: string) => state.folders === undefined ? [] : [{
    label: state.folder ? `${verb(mode)} this folder: ${state.folder.name} (${count(state.folder.eligible[mode])})` : `${verb(mode)} this folder`,
    hint, why: folderWhy(mode), onClick: () => onTransfer(mode, "folder"),
  }];

  const items: MenuEntry[] = [
    { label: "Index", hint: "Read new and changed photos from the source. Nothing is moved or copied.", why: indexWhy, onClick: onIndex },
    ...(["copy", "move"] as Mode[]).map((mode) => ({
      label: verb(mode), children: [
        { label: `${verb(mode)} selected (${count(state.selected)})`, hint: "The photos selected in the Library.",
          why: selectedWhy, onClick: () => onTransfer(mode, "selected") },
        ...folderItem(mode, "Everything in it and its subfolders."),
        { label: `${verb(mode)} all (${count(state.eligible[mode])})`, hint: allHint(mode), why: allWhy(mode),
          onClick: () => onTransfer(mode, "all") },
      ],
    })),
    // Reject and Return to library follow what is selected, wherever it is shown: Reject
    // for photos in the library, Return for photos in Rejects, both for a mix, each with
    // its own count. With neither, the view decides which one explains why.
    ...(!state.rejects ? [] : rejectItems(state.rejects, selectedWhy, onTransfer)),
  ];
  return <MenuButton label="Actions" items={items} />;
}

function rejectItems(r: { reject: number; return: number; inRejectsView: boolean }, selectedWhy: string | null,
                     onTransfer: (mode: ActionMode, scope: "selected" | "folder" | "all") => void): MenuEntry[] {
  const reject = {
    label: `Reject selected (${count(r.reject)})`,
    hint: "Move the selected photos out of the library into Rejects. Nothing is deleted.",
    why: selectedWhy ?? (r.reject === 0 ? "None of the selected photos is in the library yet. Reject works on photos already copied or moved." : null),
    onClick: () => onTransfer("reject", "selected"),
  };
  const back = {
    label: `Return selected to library (${count(r.return)})`,
    hint: "Move the selected photos from Rejects back to their date folders.",
    why: selectedWhy ?? (r.return === 0 ? "None of the selected photos is in Rejects." : null),
    onClick: () => onTransfer("return", "selected"),
  };
  if (r.reject > 0 && r.return > 0) return [reject, back];
  if (r.return > 0) return [back];
  if (r.reject > 0) return [reject];
  return [r.inRejectsView ? back : reject];
}
