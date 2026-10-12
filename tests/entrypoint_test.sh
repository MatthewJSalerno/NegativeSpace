#!/bin/sh
# Checks the container entrypoint's ownership handling against real bind
# mounts. Runs on the host, since it needs docker; the smoke suite runs inside
# the container, after the entrypoint has already done its work.
#
#   docker build -f docker/app.Dockerfile -t negativespace . && sh tests/entrypoint_test.sh
set -eu

IMAGE=${IMAGE:-negativespace}
MAPPED=4242
ME=$(id -u)
WORK=$(mktemp -d "${NS_TEST_OUTPUT_ROOT:-/tmp}/ns-entrypoint-XXXXXX")
DEST="$WORK/dest"
if [ -n "${NS_TEST_DESTINATION_ROOT:-}" ]; then DEST=$(mktemp -d "$NS_TEST_DESTINATION_ROOT/ns-entrypoint-XXXXXX"); fi
# Match mkdir's traversable destination root after ownership is handed over.
mkdir -p "$DEST"
chmod 755 "$DEST"
FAILED=0

cleanup() {
    if [ "${NS_TEST_KEEP:-0}" = 1 ]; then echo "Generated entrypoint artifacts retained."; return; fi
    # The container hands some of these to MAPPED, which this user may not be
    # able to remove.
    docker run --rm --entrypoint rm -v "$WORK":/w "$IMAGE" -rf /w/appdata >/dev/null 2>&1 || true
    docker run --rm --entrypoint find -v "$DEST":/test-dest "$IMAGE" /test-dest -mindepth 1 -delete >/dev/null 2>&1 || true
    if [ "$DEST" != "$WORK/dest" ]; then rmdir "$DEST"; fi
    rm -rf "$WORK"
}
trap cleanup EXIT

expect_owner() {
    actual=$(stat -c %u "$1")
    if [ "$actual" = "$2" ]; then
        echo "  ok    $3"
    else
        echo "  FAIL  $3 (owner $actual, expected $2)"
        FAILED=1
    fi
}

mkdir -p "$DEST/2020/01/01" "$WORK/appdata/db"
touch "$DEST/2020/01/01/existing.jpg" "$WORK/appdata/db/ns_sqlite.db"

docker run --rm -e PUID=$MAPPED -e PGID=$MAPPED \
    -v "$DEST":/data/dest -v "$WORK/appdata":/appdata \
    "$IMAGE" python3 -m engine --help >/dev/null

expect_owner "$DEST" "$MAPPED" "the destination root is handed to the mapped user"
expect_owner "$DEST/2020" "$ME" "folders already in the destination keep their owner"
expect_owner "$DEST/2020/01/01/existing.jpg" "$ME" "files already in the destination keep their owner"
expect_owner "$WORK/appdata/db/ns_sqlite.db" "$MAPPED" "appdata is handed over recursively"

exit $FAILED
