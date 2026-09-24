#!/bin/sh
# Checks that tests/make_sample_tree.sh keeps its central promise: the sample
# is built OUTSIDE the library, and the library is never written to.
#
#   sh tests/sampler_test.sh
#
# Runs on the host and needs no container — the sampler is POSIX sh and so is
# this. It is a separate file from the Python smoke suite for the same reason
# tests/entrypoint_test.sh is: the thing under test is a shell script.
#
# The sampler is pointed at an irreplaceable photo library, and it prints
# "library: N file(s), untouched" when it finishes. Every check below exists
# to keep that line honest.
set -eu

SAMPLER=$(cd "$(dirname "$0")" && pwd)/make_sample_tree.sh
WORK=$(mktemp -d)
FAILED=0

cleanup() { rm -rf "$WORK"; }
trap cleanup EXIT

ok()   { echo "  ok    $1"; }
fail() { echo "  FAIL  $1"; FAILED=1; }

# Entries, not just files: a refusal must not leave an empty directory behind
# inside the library either.
entries() { find "$1" -mindepth 1 2>/dev/null | wc -l | tr -d ' '; }
files()   { find "$1" -type f 2>/dev/null | wc -l | tr -d ' '; }

# The sampler exits non-zero on refusal, which `set -e` would turn into an
# abort of this script. Every invocation goes through here instead.
run_sampler() {
    set +e
    sh "$SAMPLER" "$@" >"$WORK/out" 2>&1
    rc=$?
    set -e
    return $rc
}

echo "sampler: $SAMPLER"

# --- 1. Normal sampling still works (regression guard) --------------------
# Spaces and nested folders included deliberately: both are ordinary in a real
# library and both are where naive quoting breaks.
lib="$WORK/t1/lib"; sample="$WORK/t1/sample"
mkdir -p "$lib/album one/2020"
: > "$lib/album one/2020/photo a.jpg"
: > "$lib/album one/2020/photo b.jpg"
: > "$lib/raw shot.dng"
: > "$lib/notes.txt"
if run_sampler "$lib" "$sample" 1; then
    # 3 photos sampled + 1 deliberate duplicate link; notes.txt is not a photo.
    if [ "$(files "$sample")" = "4" ]; then
        ok "a normal library samples every photo plus the deliberate duplicate"
    else
        fail "expected 4 files in the sample, found $(files "$sample")"
    fi
    [ "$(files "$lib")" = "4" ] \
        && ok "normal sampling leaves the library untouched" \
        || fail "normal sampling changed the library ($(files "$lib") files, expected 4)"
else
    fail "the sampler refused an ordinary library: $(cat "$WORK/out")"
fi

# --- 2. --no-raw excludes RAW ---------------------------------------------
if run_sampler --no-raw "$lib" "$WORK/t1/sample-noraw" 1; then
    [ "$(files "$WORK/t1/sample-noraw")" = "3" ] \
        && ok "--no-raw samples raster only" \
        || fail "--no-raw expected 3 files, found $(files "$WORK/t1/sample-noraw")"
else
    fail "--no-raw refused an ordinary library: $(cat "$WORK/out")"
fi

# --- 2b. A sample path several directories deep is created ----------------
# The original built the sample with `mkdir -p`, so naming a target under
# directories that do not exist yet worked. Resolving the path physically must
# not quietly take that away.
if run_sampler "$lib" "$WORK/t2b/nested/deeper/sample" 1; then
    [ "$(files "$WORK/t2b/nested/deeper/sample")" = "4" ] \
        && ok "a sample path several directories deep is created" \
        || fail "nested sample holds $(files "$WORK/t2b/nested/deeper/sample") files, expected 4"
else
    fail "refused a nested sample path that the previous version accepted: $(cat "$WORK/out")"
fi

# --- 3. A symlinked library root must not defeat the containment check ----
# `cd X && pwd` reports the LOGICAL path, so a symlinked root compares as a
# different string from the real one and a sample nested inside the library
# sails through the check.
lib2="$WORK/t2/lib"
mkdir -p "$lib2"
: > "$lib2/a.jpg"
ln -s "$lib2" "$WORK/t2/libsym"
before=$(entries "$lib2")
if run_sampler "$WORK/t2/libsym" "$lib2/inside" 1; then
    fail "built a sample INSIDE the library when the library was given as a symlink"
else
    ok "a symlinked library root is still recognised as the library"
fi
[ "$(entries "$lib2")" = "$before" ] \
    && ok "a refused symlinked root leaves the library unchanged" \
    || fail "the library gained entries ($before -> $(entries "$lib2"))"
# The sample directory is created before the containment check, so even a
# correct refusal can leave a stray directory behind inside the library.
[ ! -e "$lib2/inside" ] \
    && ok "a refusal creates nothing inside the library" \
    || fail "a directory was created inside the library before the refusal"

# --- 4. A directory symlink in the sample target must not reach the library
# `find -type f` neither counts nor descends a directory symlink, so the
# emptiness check passes and the later mkdir/ln follow it into the library.
lib3="$WORK/t3/lib"; sample3="$WORK/t3/sample"
mkdir -p "$lib3/A" "$lib3/B" "$sample3"
: > "$lib3/A/a.jpg"
ln -s "$lib3/B" "$sample3/A"   # sample/A resolves into the library
before=$(files "$lib3")
run_sampler "$lib3" "$sample3" 1 || true
[ "$(files "$lib3")" = "$before" ] \
    && ok "a directory symlink in the sample target cannot add files to the library" \
    || fail "linking through a directory symlink wrote into the library ($before -> $(files "$lib3"))"

# --- 5. A newline in a filename must not abort mid-build ------------------
# The list is newline-delimited, so such a name is split across two lines and
# the link loop then works on a truncated path. Either outcome is acceptable —
# sample it, or refuse before building anything — but not a half-built sample.
lib4="$WORK/t4/lib"; sample4="$WORK/t4/sample"
mkdir -p "$lib4"
: > "$lib4/$(printf 'odd\nname').jpg"
: > "$lib4/plain.jpg"
if run_sampler "$lib4" "$sample4" 1; then
    [ "$(files "$sample4")" -ge 2 ] \
        && ok "a newline-bearing filename is sampled rather than dropped" \
        || fail "succeeded but sampled only $(files "$sample4") file(s)"
else
    [ "$(files "$sample4")" = "0" ] \
        && ok "a newline-bearing filename is refused before anything is built" \
        || fail "aborted mid-build, leaving $(files "$sample4") file(s) in a partial sample"
fi

# --- 6. The summary must not promise an exact duplicate count -------------
# It can only know about the one duplicate it plants; a real library routinely
# contains others, and stating "1" invites reading a correct run as wrong.
if run_sampler "$lib" "$WORK/t6/sample" 1; then
    if grep -q "at least" "$WORK/out"; then
        ok "the summary states the duplicate count as a floor"
    else
        fail "the summary promises an exact duplicate count: $(grep -i duplicate "$WORK/out" | tail -1)"
    fi
else
    fail "the sampler refused an ordinary library: $(cat "$WORK/out")"
fi

# --- 7. --all-types samples non-photo files too ----------------------------
# File-type accounting counts what the Index EXCLUDES, so a sample for it must
# contain excluded files. The deliberate duplicate must still be of a photo.
lib="$WORK/t7/lib"; sample="$WORK/t7/sample"
mkdir -p "$lib/album"
: > "$lib/album/notes.txt"
: > "$lib/album/photo.jpg"
: > "$lib/album/README"
if run_sampler --all-types "$lib" "$sample" 1; then
    [ "$(files "$sample")" = "4" ] \
        && ok "--all-types samples every file plus the deliberate duplicate" \
        || fail "--all-types: expected 4 files in the sample, found $(files "$sample")"
    [ -f "$sample/duplicate_of_first.jpg" ] \
        && ok "--all-types still duplicates a photo, not a sidecar" \
        || fail "--all-types duplicated something other than the photo"
else
    fail "--all-types refused a normal library: $(cat "$WORK/out")"
fi
if run_sampler --all-types --no-raw "$lib" "$WORK/t7/other" 1; then
    fail "--all-types with --no-raw was accepted; they contradict each other"
else
    ok "--all-types with --no-raw is refused"
fi

exit $FAILED
