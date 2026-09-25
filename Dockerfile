# Pinned by digest, with requirements.txt pinned to exact versions, so a
# rebuild produces the image that was validated. Update deliberately: change
# the digest, rebuild, run CI, and validate before merging.
# The web interface's screens, built once here so the runtime image carries only the
# static files: no Node in the final image, and nothing to install on the host.
FROM node:22-slim@sha256:43ac6c60b8f89723f746e8a92ce91abd5017e627ce1ddfe4238355d3a30b772c AS frontend
WORKDIR /webui/frontend
COPY webui/frontend/package.json webui/frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY webui/frontend/ ./
RUN npm run build

FROM python:3.11-slim@sha256:9534e5a8e315485d4061ed659af0fd78a284c015f9b73661b41d6bab25604534

# Install system dependencies (ExifTool, gosu, tzdata, and build essentials for
# pillow-heif). tzdata is required for -e TZ=<zone> to have any effect: without
# the zoneinfo database the variable is silently ignored and the container stays
# on UTC, which quietly changes which YYYY/MM/DD folder a photo lands in.
RUN apt-get update && apt-get install -y --no-install-recommends \
    exiftool \
    gosu \
    tzdata \
    build-essential \
    libheif-dev \
    pkg-config \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application script and entrypoint
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
COPY ns-engine.py ns_db.py ./
COPY webui/*.py ./webui/
COPY --from=frontend /webui/static ./webui/static
RUN chmod 644 ns-engine.py

# Source and destination MUST map to separate, non-overlapping underlying
# folders. Never mount the same folder at both paths, or nest one in the other.
# Different container paths do not ensure separate storage (including NFS).
# Overlapping mounts are unsupported and can cause unintended file deletion.
# /cache holds generated thumbnails and nothing else. It is deliberately NOT
# under /appdata: everything in /appdata is irreplaceable and wants backing up,
# while every file here is reproducible from the photo it came from and is safe
# to delete at any time. Keeping them apart is also what stops the entrypoint's
# recursive chown of /appdata from walking tens of thousands of cache files on
# every start.
#
# Mounting it is optional. Unmounted, thumbnails live in the container's
# writable layer and are regenerated after the container is replaced.
#
# /backups holds catalog backups, and is deliberately NOT under /appdata for
# the opposite reason to /cache: a backup written inside the thing it is
# backing up dies with it. Losing the /appdata mount is precisely the failure
# a backup exists to survive, so it must live on a separate mount the user can
# point at different storage.
# /backups and /appdata MUST use distinct, non-overlapping backing directories:
# neither may contain the other. Different container paths alone are insufficient.
# Configure this through Docker before startup, not through application settings.
# /backups contains multiple catalog database snapshots, never photo backups.
# The engine writes a verified, Zstandard-compressed backup here after every job that
# recorded changes, and refuses (records a failed backup) when this folder is missing,
# unmounted, unwritable or overlaps /appdata.
#
# Unlike /cache these are NOT disposable — `runs` and `operations` are the only
# record of what the engine did, and since a catalog rebuild discards them, a
# backup is the sole copy of a library's history. Back this up; do not prune it
# as a cache.
# Pre-create standard volume mount points
RUN mkdir -p /data/source /data/dest /appdata/db /appdata/logs /cache /backups

# The web interface. Open http://<host>:8080 after publishing the port.
EXPOSE 8080

ENTRYPOINT ["/entrypoint.sh"]
CMD ["uvicorn", "webui.app:app", "--host", "0.0.0.0", "--port", "8080"]
