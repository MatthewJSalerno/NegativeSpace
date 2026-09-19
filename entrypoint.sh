#!/bin/sh
set -e

# Fallback defaults if PUID/PGID are not passed
PUID=${PUID:-1000}
PGID=${PGID:-1000}

# Create (or reuse) a group/user matching host UID/GID
if ! getent group "$PGID" >/dev/null 2>&1; then
    addgroup --gid "$PGID" appuser
fi
if ! getent passwd "$PUID" >/dev/null 2>&1; then
    adduser --uid "$PUID" --gid "$PGID" --disabled-password --gecos "" appuser
fi

# /appdata is the engine's own small tree (catalog, logs, lock), so all of it
# goes to the mapped user. /data/dest is the user's library: only its top
# level is taken, so new date folders can be created, and everything already
# inside keeps its owner. Walking the whole library on every start was slow
# and rewrote the ownership of the user's files.
#
# chown is expected to fail on root-squashed network shares, so a failure is
# not fatal here; the writability checks below decide what matters.
chown -R "$PUID:$PGID" /appdata 2>/dev/null || true
chown "$PUID:$PGID" /data/dest 2>/dev/null || true
# Top level only, for the same reason as /data/dest: a populated thumbnail
# cache is tens of thousands of files, and walking it on every start would be
# a cost that grows with the library.
chown "$PUID:$PGID" /cache 2>/dev/null || true
# Top level only, as above: a retained set of backups is a handful of files,
# but the same reasoning applies and the cost should not grow with them.
chown "$PUID:$PGID" /backups 2>/dev/null || true

if ! gosu "$PUID:$PGID" test -w /appdata; then
    echo "FATAL: /appdata is not writable by PUID=$PUID PGID=$PGID. Fix the ownership of the host folder mounted there." >&2
    exit 1
fi
if ! gosu "$PUID:$PGID" test -w /data/dest; then
    echo "WARNING: /data/dest is not writable by PUID=$PUID PGID=$PGID, so --move and --copy will fail. Index is unaffected." >&2
fi
if ! gosu "$PUID:$PGID" test -w /cache; then
    echo "WARNING: /cache is not writable by PUID=$PUID PGID=$PGID, so thumbnails cannot be cached and would be regenerated on every request. Nothing else is affected." >&2
fi
if ! gosu "$PUID:$PGID" test -w /backups; then
    echo "WARNING: /backups is not writable by PUID=$PUID PGID=$PGID, so catalog backups cannot be written. The catalog records what the engine did and nothing recomputes it — fix the ownership of the host folder mounted there." >&2
fi

# Drop root privileges and execute command
exec gosu "$PUID:$PGID" "$@"
