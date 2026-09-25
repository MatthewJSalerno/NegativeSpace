#!/bin/sh
# The built web interface in a real browser, end to end, arranged as in
# docker/compose.yml: an app container (API and engine) and a web container
# (screens, proxying /api to the app), driven by a Playwright container
# (tests/webui_browser_drive.py). Runs on the host because it starts containers.
# Every folder is made with mktemp under /tmp.
#
#   docker build -f docker/app.Dockerfile -t negativespace .
#   docker build -f docker/web.Dockerfile -t negativespace-web .
#   sh tests/webui_browser_test.sh
#
# SHOTS=<folder> saves screenshots of the main screens there, for review by eye.
set -eu

IMAGE=${IMAGE:-negativespace}
WEB_IMAGE=${WEB_IMAGE:-negativespace-web}
PLAYWRIGHT=mcr.microsoft.com/playwright/python:v1.63.0-noble
# Enough photos for three pages of 60, dated across two years for Jump to date.
NEWER=70
OLDER=60
DUPLICATES=2
HERE=$(cd "$(dirname "$0")" && pwd)
WORK=$(mktemp -d /tmp/ns-browser-XXXXXX)
NET=ns-browser-$$
APP=ns-browser-app-$$
WEB=ns-browser-web-$$
ME="$(id -u):$(id -g)"

cleanup() {
    docker rm -f "$WEB" >/dev/null 2>&1 || true
    docker stop -t 30 "$APP" >/dev/null 2>&1 || true
    docker rm "$APP" >/dev/null 2>&1 || true
    docker network rm "$NET" >/dev/null 2>&1 || true
    docker run --rm --entrypoint rm -v "$WORK":/w "$IMAGE" -rf /w/src /w/dest /w/appdata /w/cache /w/backups >/dev/null 2>&1 || true
    rm -rf "$WORK"
}
trap cleanup EXIT

mkdir -p "$WORK/src" "$WORK/dest" "$WORK/appdata" "$WORK/cache" "$WORK/backups"

# Distinct photos plus exact copies of the first few, made with the image's Pillow.
# The first two carry an EXIF date taken (January 2023); every other photo has none,
# so it is dated by its modification time: up to NEWER in June 2023, the rest in 2019.
docker run --rm --user "$ME" --entrypoint python3 -v "$WORK/src":/src "$IMAGE" -c "
import os
from PIL import Image
def make(name, i):
    extra = {}
    if i < 2:
        e = Image.Exif(); e.get_ifd(0x8769)[36867] = '2023:01:15 09:30:00'; extra['exif'] = e
    Image.new('RGB', (320, 240), ((i * 37) % 256, (i * 91) % 256, (i * 53) % 256)).save(name, quality=90, **extra)
    t = 1_686_000_000 if i < $NEWER else 1_560_000_000
    os.utime(name, (t, t))
for i in range($NEWER + $OLDER):
    make(f'/src/photo-{i:03d}.jpg', i)
for i in range($DUPLICATES):
    make(f'/src/copy-of-{i:03d}.jpg', i)
"

docker network create "$NET" >/dev/null
# Named "app" on the network, as in compose: the web container's nginx proxies to it.
docker run -d --name "$APP" --network "$NET" --network-alias app -e PUID="$(id -u)" -e PGID="$(id -g)" \
    -v "$WORK/src":/data/source:ro -v "$WORK/dest":/data/dest -v "$WORK/appdata":/appdata \
    -v "$WORK/cache":/cache -v "$WORK/backups":/backups "$IMAGE" >/dev/null
docker run -d --name "$WEB" --network "$NET" "$WEB_IMAGE" >/dev/null

# Wait until the API answers through the web container, rather than a fixed time.
tries=0
until docker run --rm --network "$NET" --entrypoint python3 "$IMAGE" -c \
      "import urllib.request; urllib.request.urlopen('http://$WEB:8080/api/v1/status')" >/dev/null 2>&1; do
    tries=$((tries + 1))
    if [ "$tries" -gt 60 ]; then
        echo "the web interface did not start"; docker logs "$APP"; docker logs "$WEB"; exit 1
    fi
    sleep 1
done

SHOT_ARGS=""
if [ -n "${SHOTS:-}" ]; then SHOT_ARGS="-v $SHOTS:/shots -e SHOTS=/shots"; fi
# shellcheck disable=SC2086
docker run --rm --network "$NET" $SHOT_ARGS -v "$HERE/webui_browser_drive.py":/drive.py:ro "$PLAYWRIGHT" \
    sh -c "pip install -q --root-user-action=ignore playwright==1.63.0 >/dev/null 2>&1 && python3 /drive.py http://$WEB:8080 $NEWER $OLDER $DUPLICATES" \
  || { echo "--- app log ---"; docker logs "$APP" 2>&1 | tail -40; echo "--- web log ---"; docker logs "$WEB" 2>&1 | tail -20; exit 1; }
