#!/bin/sh
# Builds a small, hard-linked sample of a photo library, for validating a
# change against real files without waiting for the whole library.
#
#   sh tests/make_sample_tree.sh <library> <sample> [every-Nth]
#
# Hard links cost no disk space and share the original's bytes, mtime and
# EXIF, so the sample behaves like the real library at a fraction of the wall
# clock: ~500 files run Index, Copy and Move in about 30 seconds where a
# 12,500-file library takes ~36 minutes.
#
# The sample also gets ONE DELIBERATE DUPLICATE — a second link to a file
# already sampled. This matters more than it looks. Sampling alone can miss
# duplicates entirely (a library holding two duplicate pairs in 12,505 files
# yields none at every 25th file), and a sample with no duplicates silently
# skips duplicate cleanup, which is the engine's riskiest path because it is
# the one that deletes. A second link to an existing file IS an exact
# duplicate by construction, so it costs nothing and is always present.
#
# Removing files from the sample never touches the library: deleting one link
# leaves the original and its other links intact. That is what makes it safe
# to point --move at this tree.
#
# POSIX sh on purpose: the NAS side runs BusyBox, which has neither
# `cp --parents` nor `cpio -l`.
set -eu

usage() {
    echo "usage: sh tests/make_sample_tree.sh <library> <sample> [every-Nth, default 25]" >&2
    echo "   eg: sh tests/make_sample_tree.sh /photos/library /photos/sample 25" >&2
    exit 2
}

[ $# -ge 2 ] || usage
LIBRARY=$1
SAMPLE=$2
NTH=${3:-25}

case "$NTH" in
    ""|*[!0-9]*) echo "every-Nth must be a whole number, got: $NTH" >&2; exit 2 ;;
esac
[ "$NTH" -ge 1 ] || { echo "every-Nth must be at least 1, got: $NTH" >&2; exit 2; }
[ -d "$LIBRARY" ] || { echo "library is not a directory: $LIBRARY" >&2; exit 2; }

LIB_ABS=$(cd "$LIBRARY" && pwd)
mkdir -p "$SAMPLE"
SAMPLE_ABS=$(cd "$SAMPLE" && pwd)

# The sample must sit OUTSIDE the library. A sample nested inside it gets
# indexed as part of the library on the next run, and every sampled photo
# then looks like a duplicate of itself.
[ "$SAMPLE_ABS" != "$LIB_ABS" ] || {
    echo "refusing: the sample and the library are the same directory" >&2; exit 2; }
case "$SAMPLE_ABS/" in "$LIB_ABS"/*)
    echo "refusing: the sample would sit inside the library ($SAMPLE_ABS)" >&2
    echo "          put it alongside the library, not within it" >&2
    exit 2 ;;
esac
case "$LIB_ABS/" in "$SAMPLE_ABS"/*)
    echo "refusing: the library sits inside the sample ($LIB_ABS)" >&2; exit 2 ;;
esac

existing=$(find "$SAMPLE_ABS" -type f | wc -l)
[ "$existing" -eq 0 ] || {
    echo "refusing: $SAMPLE_ABS already holds $existing file(s)" >&2
    echo "          a partial sample skews every count; clear it first" >&2
    exit 2 ; }

LIST=$(mktemp)
trap 'rm -f "$LIST"' EXIT

# Relative paths, so the sample reproduces the library's folder structure.
# Flattening instead would collide same-named photos from different albums.
cd "$LIB_ABS"
find . -type f \
    \( -iname '*.jpg' -o -iname '*.jpeg' -o -iname '*.png' -o -iname '*.heic' \
       -o -iname '*.heif' -o -iname '*.tif' -o -iname '*.tiff' \) \
    | awk -v n="$NTH" '(NR - 1) % n == 0' > "$LIST"

count=0
while IFS= read -r rel; do
    mkdir -p "$SAMPLE_ABS/${rel%/*}"
    ln "$LIB_ABS/$rel" "$SAMPLE_ABS/$rel"
    count=$((count + 1))
done < "$LIST"

[ "$count" -gt 0 ] || {
    echo "no photos matched under $LIB_ABS — nothing sampled" >&2; exit 1; }

first=$(head -n 1 "$LIST")
ext=${first##*.}
ln "$SAMPLE_ABS/$first" "$SAMPLE_ABS/duplicate_of_first.$ext"

total=$(find "$SAMPLE_ABS" -type f | wc -l)
echo "sampled   : $count photo(s), 1 in $NTH matches under $LIB_ABS"
echo "duplicate : duplicate_of_first.$ext — a second link to the first sampled photo"
echo "sample    : $total file(s) in $SAMPLE_ABS"
echo "library   : $(find "$LIB_ABS" -type f | wc -l) file(s), untouched"
echo
echo "Index and Copy should report $count delivered and 1 skipped duplicate."
