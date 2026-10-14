# Installation details

The [README](../README.md#install) covers a standard install. This page covers the rest:
what each folder holds, network shares, network access, writing your own compose file,
and stopping a job.

## Folders

| Container path | Set by | Holds |
| --- | --- | --- |
| `/data/source` | `SOURCE_DIR` | Your photos, as they are |
| `/data/dest` | `DEST_DIR` | `library/`, the organized photos; `rejects/`, the photos you reject |
| `/appdata` | `APPDATA_DIR` | The catalog (`db/`) and logs (`logs/`) |
| `/backups` | `BACKUP_DIR` | Catalog backups |
| `/cache` | a named Docker volume | Thumbnails |

> **Never mount source and destination to the same underlying folder, or place either
> folder inside the other.** Different container paths do not make the storage separate.
> Check the host folders and network-share mappings, NFS included. NegativeSpace refuses
> to start when it can see an overlap (the same folder, one inside the other, or one
> folder mounted at both paths), and it never deletes a source that turns out to be the
> same file as its copy. It cannot see every alias, though, such as two separate network
> mounts of one share. This setup is unsupported.

### Source

Index and Copy only read it, so `docker/compose.yml` mounts it read-only. **Move needs a
writable source:** with a read-only one, Move can only copy, and each photo shows
**Copied only** with the reason. To Move, set `read_only: false` on the source volume in
`docker/compose.yml`, recreate the containers, and Move the photos again.

NegativeSpace handles only the photo types it supports (see [Files it handles](#files-it-handles)).
Everything else in the source (videos, sidecars, documents) is left where it is, so a Move
does not empty the source folder. Expect those leftovers.

### Destination

Organized photos go to `library/YYYY/MM/DD/`. A photo with no usable date goes to
`library/Undated/<year>/` instead, where the year comes from the file's modification time.
Rejected photos go to `rejects/`, which you empty yourself.

`library/` is laid out for your gallery app of choice, such as Immich, to read. `rejects/`
sits beside it rather than inside it, so photos you turn down stay out of your gallery.

### App data

The catalog: every photo's details and the history of everything done to it. **It is
irreplaceable.** An Index can rebuild the list of photos, but nothing can recreate the
history of what was copied, moved or rejected. Include this folder in your own backups.

### Backups

After every Index, Copy or Move that changed something, NegativeSpace writes one verified,
compressed snapshot of the catalog here (`ns-catalog-<time>-<attempt>-<trigger>.db.zst`).
A catalog of about 520 MB compresses to about 20 MB. **Back up now** in **Settings ›
Backups** writes one by hand. The latest 20 automatic backups are kept; older ones are
removed only after a newer one succeeds, and manual backups are never removed.

- **It must be a mounted folder.** Without a mount, `/backups` is a folder inside the
  container that would disappear with it, so NegativeSpace records the backup as failed
  instead of writing it. A failed backup never changes the job's own result.
- **Keep it apart from app data.** A backup stored inside the folder it backs up is lost
  along with it. Use different storage if you can.
- **It holds no photos.** Restoring a backup brings back the catalog, not a single photo.
  See [If something goes wrong](recovery.md#restore-a-catalog-backup).

### Thumbnails

Thumbnails live in the `/cache` volume, under `thumbnails/<first two characters of the
hash>/<content hash>.jpg`. They are keyed by content, so identical photos share one, and
the cache survives a catalog rebuild. Everything here can be rebuilt from the photos, so
**leave it out of your backups**. The named volume keeps thumbnails when the container is
replaced.

## Your user and time zone

**`PUID` / `PGID`** run NegativeSpace as your host user, so the files it writes belong to
you. On start, the container gives that user all of `/appdata` but only the top level of
`/data/dest`; folders and files already in the destination keep their owners, so use the
same `PUID`/`PGID` every time. The container refuses to start if `/appdata` is not writable
by that user, and warns if `/data/dest` is not.

New catalog and backup files are readable only by that user (`0600`). Photo permissions
are not changed. Use the same account for any outside backup of these folders.

**`TZ`** matters only for photos with no usable EXIF date, which are dated by their file's
modification time. A container runs in UTC unless told otherwise, so a file modified at
21:00 in New York would be read as the next day. Set `TZ` to your zone (for example
`America/New_York`). Photos with an EXIF date are unaffected: those dates carry no time
zone and are used exactly as the camera recorded them.

## Network access

**There is no sign-in yet.** Anyone who can open the page can use every button, including
**Move**. Keep NegativeSpace on your own network, never forward its port to the internet,
and from elsewhere use a VPN or a reverse proxy that asks for a password first (such as
Authelia, Authentik, or nginx with basic authentication). A single password is planned
before the first release.

**Allowed addresses.** NegativeSpace answers only to addresses it knows. `localhost` and
the local loopback addresses always work. To use a LAN address, hostname or reverse-proxy
name, either:

- add it in setup or **Settings › Access**, which takes effect without a restart; or
- add it to `NS_ALLOWED_HOSTS` in `docker/.env`, separated by commas, and recreate the
  containers. Use this to reach a headless server for the first time.

Use exact names: no scheme, port or wildcard. Case is ignored. Any other address gets
`400 untrusted_host`. Addresses saved in Settings are kept apart from the catalog, so they
survive replacing or restoring it. Addresses from `NS_ALLOWED_HOSTS` and the local ones
cannot be removed in Settings, so they always remain a way back in.

**Behind a reverse proxy,** pass the public `Host` header through unchanged, including its
port. Forwarded-host headers never grant access. The live job feed follows the same rules.

**What this does not do.** Allowed addresses and same-origin checks stop other web pages
from driving the app, and other sites cannot embed it in a frame. They do not identify who
is using it and do not protect against DNS rebinding, which is why the network rules above
still apply.

## Network shares

- **Destination on a network share.** A share exported `async` can report data as saved
  before it reaches the server's disk, and NegativeSpace cannot see how a share is
  exported. So a Move to a network share stops and asks first. Copy is never stopped,
  because it never deletes a source. Confirm a Move only for a share exported `sync`.
- **App data on a network share.** NegativeSpace allows only one job at a time per app
  data folder, using a file lock. Locks over NFS depend on the server's lock services;
  local disk or a standard Docker volume is the safe choice for `/appdata`. A source on
  NFS has no effect on this.

## One catalog per destination

Use one app data folder per destination. Two NegativeSpace instances writing to the same
destination with different app data folders don't know about each other. Your photos are
not at risk, because a source is deleted only after the instance deleting it has verified
its own copy. You would get unexplained failures and the same photo delivered twice under
different names instead. Several sources feeding one destination through one instance is
fine.

## Stopping and cancelling

**Cancel job** in the progress bar stops a job cleanly; so does `docker compose down` or
`docker stop`. A cancelled job finishes the file it is copying, records the photos it did
not reach as Cancelled, and takes a catalog backup. Closing the browser does not stop a
job, and restarting the containers never restarts one.

Docker normally kills a container 10 seconds after asking it to stop, and one large file
over a network share can take longer than that. `docker/compose.yml` sets
`stop_grace_period: 5m` to allow for it. A job killed before it settles is not lost: the
next start records it as Interrupted and checks every file it left mid-way.

**If a job seems stuck,** with progress stopped while the container stays up, a network
mount has usually stopped answering. `docker stop` is safe here: the lock is released
immediately, the next start settles the interrupted job, and a Move that stalled leaves
its source file where it is. Nothing needs cleaning up by hand.

## Things that look wrong but aren't

- **`/appdata/engine.lock` is always there,** even when nothing is running. The file is
  only something to hold a lock on; the lock itself disappears when the process ends,
  however it ends. You never need to delete it.
- **The source isn't empty after a Move.** Files NegativeSpace doesn't handle stay where
  they are.

## Files it handles

36 file types: 13 standard image formats (`.jpg`, `.jpeg`, `.jpe`, `.jfif`, `.png`,
`.gif`, `.bmp`, `.webp`, `.tif`, `.tiff`, `.heic`, `.heif`, `.avif`) and 23 RAW formats
(`.raw`, `.dng`, `.cr2`, `.cr3`, `.crw`, `.nef`, `.nrw`, `.arw`, `.srf`, `.sr2`, `.raf`,
`.orf`, `.rw2`, `.pef`, `.ptx`, `.srw`, `.erf`, `.3fr`, `.fff`, `.iiq`, `.mos`, `.mrw`,
`.x3f`). Choose which ones to include in setup or **Settings › Files**.

## Catalog versions

Before version 1.0.0, a catalog made by an older version is **refused, not upgraded**.
Keep the old catalog folder, let NegativeSpace create a fresh one, and run Index: the list
of photos comes back from your source, but the old history stays in the old catalog.

## Writing your own compose file

If you write your own compose file instead of using `docker/compose.yml`, save it in
`docker/`, beside the Dockerfiles. The essentials:

```yaml
services:
  web:
    build:
      context: ..
      dockerfile: docker/web.Dockerfile
    ports:
      - "8080:8080"
    depends_on:
      - app

  app:                            # the web container sends /api to "app"
    build:
      context: ..                 # the images build from the repository root
      dockerfile: docker/app.Dockerfile
    environment:
      PUID: 1000
      PGID: 1000
      NS_ALLOWED_HOSTS: localhost,127.0.0.1,0.0.0.0,::1  # add LAN and proxy names
      TZ: America/New_York
    volumes:
      - /path/to/your/photos:/data/source:ro
      - /path/to/organized:/data/dest
      - /path/to/appdata:/appdata
      - /path/to/backups:/backups
      - cache:/cache
    stop_grace_period: 5m         # lets a cancelled job finish the file it is copying

volumes:
  cache:
```

The shipped [`docker/compose.yml`](../docker/compose.yml) also checks that every folder
exists before starting.

To show the exact build beside the version number at the foot of the sidebar, build with
`NS_BRANCH=$(git branch --show-current) NS_COMMIT=$(git rev-parse --short HEAD) docker compose up -d --build`.
