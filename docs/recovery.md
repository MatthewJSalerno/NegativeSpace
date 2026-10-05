# If something goes wrong

> **NegativeSpace does not back up your photos. That is your job.**
> The backups it makes are of its **catalog**: what it knows about your photos and the
> history of everything it has done to them. A catalog backup holds **no photos** and
> cannot bring back a single one. Keep your own backups of your photos, and of the
> destination folder once NegativeSpace has organized them, with whatever you already
> use for backups.

NegativeSpace keeps three things, and only one of them is protected by its own backups:

| What | Where | Who backs it up |
| --- | --- | --- |
| Your organized photos | The destination folder (`DEST_DIR`) | **You** |
| Your original photos, before a Move | The source folder (`SOURCE_DIR`) | **You** |
| The catalog: each photo's details and full history | The app data folder (`APPDATA_DIR`) | NegativeSpace, into the backup folder (`BACKUP_DIR`) after every job that changes it. Include that folder in your own backups too. |

## What to do

| What went wrong | What you can get back | What to do |
| --- | --- | --- |
| The catalog is lost or damaged (the page says the catalog cannot be opened) | The catalog as of its last backup. Anything done since is missing from the history, though the photos themselves are where those jobs left them. | [Restore a catalog backup](#restore-a-catalog-backup). |
| The power went out, or the container was killed, during a job | Everything. | Nothing: start it again. The next job records the interrupted one as Interrupted and settles each photo it left half done, keeping the original whenever it cannot prove the copy is good. |
| The destination disk failed | After **Copy**: everything, because your originals were never touched. After **Move**: only what your own backups hold, because the originals were deleted once their copies were verified. | Restore the destination from your backups, or Copy again from the source. Then run an Index so the catalog sees what is there. |
| Rejects was emptied by mistake | Nothing from NegativeSpace: it never deletes photos, and so never keeps them either. The photos' history is still in the catalog. | Restore the files from your own backups into the `rejects` folder, then run an Index. |
| A photo was deleted or changed outside NegativeSpace | Only what your own backups hold. | Restore it from your backups; the next Index records what it finds. |
| The whole computer failed | Whatever your own backups hold. | Install NegativeSpace again, restore your destination and backup folders, then [restore the newest catalog backup](#restore-a-catalog-backup). |

## Restore a catalog backup

1. Stop NegativeSpace: `docker compose down` in the `docker/` folder.
2. In the app data folder, open `db/` and move `ns_sqlite.db`, and any
   `ns_sqlite.db-wal` and `ns_sqlite.db-shm` beside it, somewhere else. Do not delete them
   until the restore works.
3. Pick a backup in the backup folder. Names start with the time, in UTC:
   `ns-catalog-<time>-<attempt>-<trigger>.db.zst`.
4. Decompress it with `zstd -d <file>.db.zst`. [Zstandard's page](https://facebook.github.io/zstd/)
   links the command-line tool and the Windows archive managers that open `.zst` files.
5. Copy the resulting `.db` into `db/` as `ns_sqlite.db`.
6. Start NegativeSpace again: `docker compose up -d`.

A restored catalog does not change any photo. It only brings back what NegativeSpace
knew at that moment; run an Index afterwards so it catches up with the folders.
