// The screens before the Library: creating a catalog, and a catalog that cannot be opened.
import { useState } from "react";
import { api, ApiError, type Status } from "../api";
import { Logo } from "./Logo";
import { versionText } from "./VersionTag";

export function FirstRun({ status, onCreated }: { status: Status; onCreated: () => void }) {
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const create = async () => {
    setBusy(true);
    setError(null);
    try {
      await api.createCatalog();
      onCreated();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "The catalog could not be created.");
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="center-page">
      <div className="panel">
        <h1 className="brand brand-large"><Logo height={48} />NegativeSpace</h1>
        <p>
          No catalog found. If this is your first time using NegativeSpace, create a catalog to get started.
          If you've used it before, check the folders below, or recover your catalog from a backup.
        </p>
        <MountsNote status={status} />
        <p className="muted">{versionText(status.version)}</p>
        {error && <p className="error">{error}</p>}
        <button className="primary" onClick={create} disabled={busy}>{busy ? "Creating…" : "Create new catalog"}</button>
      </div>
    </div>
  );
}

// Where the catalog and its backups are, said so that nobody searches their disk for
// "/appdata": these are paths inside the container, each a folder of the user's choosing,
// and the app cannot see which (webui-spec 2, startup without a usable catalog).
function MountsNote({ status }: { status: Status }) {
  return (
    <div className="mounts-note">
      <p>NegativeSpace looks for:</p>
      <ul>
        <li>its catalog in <code>{status.application_data}</code></li>
        <li>catalog backups in <code>{status.catalog_backups}</code></li>
      </ul>
      <p>These are paths inside the container, not folders on your computer.</p>
      <p>Each is a folder on your computer that you chose when you set up NegativeSpace:</p>
      <ul>
        <li>with the included <code>docker/compose.yml</code>: <code>APPDATA_DIR</code> and <code>BACKUP_DIR</code> in <code>docker/.env</code></li>
        <li>with <code>docker run</code>: its <code>-v</code> options</li>
      </ul>
      <p>If you've used NegativeSpace before, check that they still name the same folders, and that those
        folders are reachable: a network share or USB drive can be disconnected.</p>
    </div>
  );
}

export function CatalogProblem({ status }: { status: Status }) {
  return (
    <div className="center-page">
      <div className="panel">
        <h1>{status.state === "incompatible" ? "This catalog cannot be opened" : "The catalog could not be read"}</h1>
        <p>{status.detail}</p>
        <p>
          Nothing was changed. {status.state === "incompatible"
            ? "It was made by a different version of NegativeSpace. Recover a compatible catalog from a backup, or point the application data folder below at another catalog."
            : "Check that the application data folder is mounted and readable by the container, and that its storage is connected."}
        </p>
        <MountsNote status={status} />
        <p className="muted">{versionText(status.version)}</p>
      </div>
    </div>
  );
}