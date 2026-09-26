#!/bin/sh
# Stopping the app container while a browser is open on it. The job feed's WebSocket
# stays open as long as the page does, and uvicorn runs the app's shutdown (which
# cancels a running job cleanly, JobRunner.shutdown) only after every connection has
# ended. A feed that never notices the connection closing held the container until
# docker killed it: with compose's 5-minute grace period, a Move in progress was never
# cancelled, only killed. Runs on the host, since it needs docker.
#
#   docker build -f docker/app.Dockerfile -t negativespace . && sh tests/shutdown_test.sh
set -eu

IMAGE=${IMAGE:-negativespace}
WORK=$(mktemp -d /tmp/ns-shutdown-XXXXXX)
NET=ns-shutdown-$$
APP=ns-shutdown-app-$$
TAB=ns-shutdown-tab-$$
FAILED=0

cleanup() {
    docker rm -f "$APP" "$TAB" >/dev/null 2>&1 || true
    docker network rm "$NET" >/dev/null 2>&1 || true
    docker run --rm --entrypoint rm -v "$WORK":/w "$IMAGE" -rf /w/src /w/dest /w/appdata /w/backups /w/cache >/dev/null 2>&1 || true
    rm -rf "$WORK"
}
trap cleanup EXIT

mkdir -p "$WORK/src" "$WORK/dest" "$WORK/appdata" "$WORK/backups" "$WORK/cache"
docker network create "$NET" >/dev/null
docker run -d --name "$APP" --network "$NET" --network-alias app -e PUID="$(id -u)" -e PGID="$(id -g)" \
    -v "$WORK/src":/data/source -v "$WORK/dest":/data/dest -v "$WORK/appdata":/appdata \
    -v "$WORK/backups":/backups -v "$WORK/cache":/cache "$IMAGE" >/dev/null
for _ in $(seq 60); do
    docker exec "$APP" python3 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/status')" \
        >/dev/null 2>&1 && break
    sleep 1
done

# A browser tab: connected to the job feed, never sending, until the server closes it.
docker run -d --name "$TAB" --network "$NET" --entrypoint python3 "$IMAGE" -c "
import asyncio, websockets
async def main():
    async with websockets.connect('ws://app:8000/api/v1/ws/jobs') as ws:
        while True:
            await ws.recv()
asyncio.run(main())" >/dev/null
for _ in $(seq 20); do
    docker logs "$APP" 2>&1 | grep -q "connection open" && break
    sleep 0.5
done

start=$(date +%s)
docker stop -t 30 "$APP" >/dev/null
took=$(( $(date +%s) - start ))
code=$(docker inspect -f '{{.State.ExitCode}}' "$APP")

if [ "$code" = 0 ] && [ "$took" -le 10 ]; then
    echo "  ok    stopped in ${took}s with a job feed open, exit 0"
else
    echo "  FAIL  took ${took}s to stop with a job feed open, exit $code (137: killed at the grace period)"
    FAILED=1
fi
if docker logs "$APP" 2>&1 | grep -q "Application shutdown complete"; then
    echo "  ok    the app's shutdown ran (it cancels a running job)"
else
    echo "  FAIL  the app's shutdown never ran, so a running job would be killed, not cancelled"
    FAILED=1
fi

[ "$FAILED" = 0 ] && echo "shutdown: ok"
exit "$FAILED"
