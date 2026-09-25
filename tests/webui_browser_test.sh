#!/bin/sh
# The built web interface in a real browser, end to end: the image serves it, a
# Playwright container drives it (tests/webui_browser_drive.py). Runs on the host
# because it starts two containers. Every folder is made with mktemp under /tmp.
#
#   docker build -t negativespace . && sh tests/webui_browser_test.sh
set -eu

IMAGE=${IMAGE:-negativespace}
PLAYWRIGHT=mcr.microsoft.com/playwright/python:v1.63.0-noble
PHOTOS=24
DUPLICATES=2
HERE=$(cd "$(dirname "$0")" && pwd)
WORK=$(mktemp -d /tmp/ns-browser-XXXXXX)
NET=ns-browser-$$
SERVER=ns-browser-server-$$
ME="$(id -u):$(id -g)"

cleanup() {
    docker stop -t 30 "$SERVER" >/dev/null 2>&1 || true
    docker rm "$SERVER" >/dev/null 2>&1 || true
    docker network rm "$NET" >/dev/null 2>&1 || true
    docker run --rm --entrypoint rm -v "$WORK":/w "$IMAGE" -rf /w/src /w/dest /w/appdata /w/cache /w/backups >/dev/null 2>&1 || true
    rm -rf "$WORK"
}
trap cleanup EXIT

mkdir -p "$WORK/src" "$WORK/dest" "$WORK/appdata" "$WORK/cache" "$WORK/backups"

# Distinct photos plus exact copies of the first few, made with the image's Pillow.
docker run --rm --user "$ME" --entrypoint python3 -v "$WORK/src":/src "$IMAGE" -c "
from PIL import Image
for i in range($PHOTOS):
    Image.new('RGB', (640, 480), ((i * 37) % 256, (i * 91) % 256, (i * 53) % 256)).save(f'/src/photo-{i:03d}.jpg', quality=90)
for i in range($DUPLICATES):
    Image.new('RGB', (640, 480), ((i * 37) % 256, (i * 91) % 256, (i * 53) % 256)).save(f'/src/copy-of-{i:03d}.jpg', quality=90)
"

docker network create "$NET" >/dev/null
docker run -d --name "$SERVER" --network "$NET" -e PUID="$(id -u)" -e PGID="$(id -g)" \
    -v "$WORK/src":/data/source:ro -v "$WORK/dest":/data/dest -v "$WORK/appdata":/appdata \
    -v "$WORK/cache":/cache -v "$WORK/backups":/backups "$IMAGE" >/dev/null

# Wait for the server rather than sleeping a fixed time.
tries=0
until docker run --rm --network "$NET" --entrypoint python3 "$IMAGE" -c \
      "import urllib.request; urllib.request.urlopen('http://$SERVER:8080/api/v1/status')" >/dev/null 2>&1; do
    tries=$((tries + 1))
    if [ "$tries" -gt 60 ]; then
        echo "the server did not start"; docker logs "$SERVER"; exit 1
    fi
    sleep 1
done

docker run --rm --network "$NET" -v "$HERE/webui_browser_drive.py":/drive.py:ro "$PLAYWRIGHT" \
    sh -c "pip install -q --root-user-action=ignore playwright==1.63.0 >/dev/null 2>&1 && python3 /drive.py http://$SERVER:8080 $PHOTOS $DUPLICATES" \
  || { echo "--- server log ---"; docker logs "$SERVER" 2>&1 | tail -40; exit 1; }
