import { Tip } from "./Tip";
import { useState } from "react";
import type { FolderNode, FolderTree } from "../api";
import { count, plural } from "../format";

// The files directly in the source folder, which no subfolder holds (GET /photos/folders).
export const TOP_FILES = ".";

export function folderLabel(path: string): string {
  return path === TOP_FILES ? "files in the source folder" : path.split("/").join(" / ");
}

// The source's folders, as the Index catalogued them, with "Show only" boxes (webui-spec
// 2). A ticked folder takes its subfolders, which show ticked and cannot be unticked on
// their own; a folder some of whose subfolders are ticked shows a dash. Counts follow
// the view, search, dates and types, never this filter, so an unticked folder keeps
// its number. Long names end in "…", with the whole path on hover.
export function FoldersPanel({ tree, folders, onFolders, heading = "Folders" }: {
  tree: FolderTree | null;
  folders: string[];
  onFolders: (folders: string[]) => void;
  heading?: string;
}) {
  const [open, setOpen] = useState<Set<string>>(() => {
    const ancestors = new Set<string>();
    for (const f of folders) {
      const parts = f.split("/");
      for (let i = 1; i < parts.length; i++) ancestors.add(parts.slice(0, i).join("/"));
    }
    return ancestors;
  });
  if (!tree) return null;
  const within = (path: string, folder: string) => path === folder || path.startsWith(`${folder}/`);
  const includedBy = (path: string) => folders.find((f) => f !== TOP_FILES && f !== path && within(path, f));
  const ticked = (path: string) => folders.includes(path) || !!includedBy(path);
  const partly = (path: string) => !ticked(path) && folders.some((f) => f.startsWith(`${path}/`));
  const toggle = (path: string) => onFolders(folders.includes(path)
    ? folders.filter((f) => f !== path)
    : [...folders.filter((f) => !f.startsWith(`${path}/`)), path]);
  const fold = (path: string) => setOpen((cur) => {
    const next = new Set(cur);
    if (next.has(path)) next.delete(path); else next.add(path);
    return next;
  });

  const row = (node: FolderNode, depth: number) => {
    const isOpen = open.has(node.path);
    const parent = includedBy(node.path);
    const id = `folder-${node.path}`;
    return (
      <li key={node.path}>
        <div className={`dates-row folder-row${node.photos === 0 ? " folder-empty" : ""}`} style={{ paddingLeft: 4 + depth * 16 }}>
          <input type="checkbox" id={id} checked={ticked(node.path)} disabled={!!parent}
                 title={parent ? `Included in ${folderLabel(parent)}` : undefined}
                 ref={(el) => { if (el) el.indeterminate = partly(node.path); }}
                 onChange={() => toggle(node.path)} aria-label={`Show only ${folderLabel(node.path)}`} />
          {node.folders.length > 0 ? (
            <button className="dates-caret" aria-expanded={isOpen}
                    aria-label={isOpen ? `Fold ${node.name}` : `Unfold ${node.name}`} onClick={() => fold(node.path)}>
              {isOpen ? "▾" : "▸"}
            </button>
          ) : <span className="dates-caret" />}
          <label htmlFor={id} className="dates-name folder-name" title={folderLabel(node.path)}>{node.name}</label>
          <span className="dates-count">{count(node.photos)}</span>
        </div>
        {isOpen && node.folders.length > 0 && <ul>{node.folders.map((child) => row(child, depth + 1))}</ul>}
      </li>
    );
  };

  const top = tree.top_files.photos > 0 || folders.includes(TOP_FILES);
  return (
    <nav className="dates-panel folders-panel" aria-label={heading}>
      <div className="dates-head">
        <h2>{heading}</h2>
        <Tip text="Check folders to show only the photos in them, subfolders included. Uncheck them all to show everything."><span className="dates-show-only">Show only</span></Tip>
      </div>
      <p className="dates-status muted">
        <span title={folders.length ? `Showing only ${folders.map(folderLabel).join(", ")}` : undefined}>{folders.length === 0 ? "Showing all folders" : `Showing only ${folders.map(folderLabel).join(", ")}`}</span>
        <button className="link" style={{ visibility: folders.length ? undefined : "hidden" }} disabled={!folders.length} aria-hidden={!folders.length || undefined} onClick={() => onFolders([])}>Show all</button>
      </p>
      <ul className="dates-tree">
        {tree.folders.map((node) => row(node, 0))}
        {top && (
          <li>
            <div className="dates-row folder-row" style={{ paddingLeft: 4 }}>
              <input type="checkbox" id="folder-top" checked={folders.includes(TOP_FILES)} onChange={() => toggle(TOP_FILES)}
                     aria-label="Show only the files in the source folder" />
              <span className="dates-caret" />
              <label htmlFor="folder-top" className="dates-name folder-name"
                     title="Photos directly in the source folder, in no subfolder">Files in the source folder</label>
              <span className="dates-count">{count(tree.top_files.photos)}</span>
            </div>
          </li>
        )}
      </ul>
      {tree.outside > 0 && (
        <p className="dates-foot muted">{plural(tree.outside, "photo")} from another source folder, not in this tree.</p>
      )}
    </nav>
  );
}

// The one folder shown, for the Jobs menu's "this folder", found in the tree; null unless
// exactly one real folder is ticked.
export function shownFolder(tree: FolderTree | null, folders: string[]): FolderNode | null {
  if (!tree || folders.length !== 1 || folders[0] === TOP_FILES) return null;
  const find = (nodes: FolderNode[]): FolderNode | null => {
    for (const n of nodes) {
      if (n.path === folders[0]) return n;
      if (folders[0].startsWith(`${n.path}/`)) return find(n.folders);
    }
    return null;
  };
  return find(tree.folders);
}
