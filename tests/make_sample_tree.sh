#!/bin/sh
# Builds a small, hard-linked sample of a photo library, for validating a
# change against real files without waiting for the whole library.
#
#   sh tests/make_sample_tree.sh [--no-raw | --all-types] <library> <sample> [every-Nth]
#
# --all-types samples every file, not only photos: sidecars, videos, previews,
# files with no extension. That is what exercises the Index's file-type
# accounting, which counts what a walk EXCLUDES; a photos-only sample reports
# zero excluded files and so proves nothing about it.
#
# Hard links cost no disk space and share the original's bytes, mtime and
# EXIF, so the sample behaves like the library at a fraction of the wall
# clock: ~500 raster files run Index, Copy and Move in about 30 seconds where
# a 12,500-file library takes ~36 minutes.
#
# RAW is included by default. It is the path most likely to be skipped by
# accident — rawpy is a hard dependency and 23 RAW extensions are advertised,
# yet nothing decoded a real RAW file in this project until a fixture was
# built by hand. A sampler that quietly omitted them would keep it that way.
# --no-raw trades that coverage for size and speed: RAW files run ~20-25 MB
# against ~300 KB for a JPEG, so including them makes a sample many times
# larger to copy.
#
# The sample also gets ONE DELIBERATE DUPLICATE — a second link to a file
# already sampled. Sampling alone can miss duplicates entirely (a library
# holding two duplicate pairs in 12,505 files yields none at every 25th
# file), and a sample with no duplicates silently skips duplicate cleanup,
# which is the engine's riskiest path because it is the one that deletes. A
# second link to an existing file IS an exact duplicate by construction.
#
# Removing files from the sample never touches the library: deleting one link
# leaves the original and its other links intact. That is what makes it safe
# to point --move at this tree.
#
# Plain POSIX sh, but no longer for BusyBox. This once claimed to target the
# NAS shell so a sample could be built there; the maintainer runs it from the
# workstation over NFS instead, where `ln` creates the link server-side anyway,
# so that path was never exercised and the claim was never tested. It is
# dropped rather than verified — an unenforced claim is worth less than none,
# which is the rule the durability table in TODO.md applies to itself.
#
# Nothing here needs bashisms, so it stays POSIX by preference rather than by
# obligation.
#
# Before sampling, the library is walked twice to prove no filename contains a
# newline (see below). Measured at ~3.6s over 54,000 files on an NFS mount —
# paid once, against a run that then takes minutes, and it is what stops a
# half-built sample.
set -eu

usage() {
    echo "usage: sh tests/make_sample_tree.sh [--no-raw | --all-types] <library> <sample> [every-Nth, default 25]" >&2
    echo "   eg: sh tests/make_sample_tree.sh /photos/library /photos/sample 25" >&2
    echo "       --no-raw     sample only raster formats; smaller and faster, no RAW coverage" >&2
    echo "       --all-types  sample every file, not only photos (exercises file-type accounting)" >&2
    exit 2
}

INCLUDE_RAW=1
ALL_TYPES=0
while [ $# -gt 0 ]; do
    case "$1" in
        --no-raw) INCLUDE_RAW=0; shift ;;
        --all-types) ALL_TYPES=1; shift ;;
        -h|--help) usage ;;
        --) shift; break ;;
        -*) echo "unknown option: $1" >&2; usage ;;
        *) break ;;
    esac
done

[ $# -ge 2 ] || usage
[ "$ALL_TYPES" -eq 0 ] || [ "$INCLUDE_RAW" -eq 1 ] || {
    echo "--all-types and --no-raw contradict each other: pick one" >&2; exit 2; }
LIBRARY=$1
SAMPLE=$2
NTH=${3:-25}

case "$NTH" in
    ""|*[!0-9]*) echo "every-Nth must be a whole number, got: $NTH" >&2; exit 2 ;;
esac
[ "$NTH" -ge 1 ] || { echo "every-Nth must be at least 1, got: $NTH" >&2; exit 2; }
[ -d "$LIBRARY" ] || { echo "library is not a directory: $LIBRARY" >&2; exit 2; }

# PHYSICAL paths, resolved with `pwd -P`. Plain `pwd` reports the LOGICAL path,
# so a symlinked root compares as a different string from the real one and a
# sample nested inside the library passes the checks below — after which the
# link loop writes into the library itself. Symlinked mounts and aliased share
# names are ordinary, so this is not an exotic case.
LIB_ABS=$(cd "$LIBRARY" && pwd -P)

# The sample is resolved WITHOUT being created: creating it first left a stray
# directory inside the library even when the check below then refused. Walk up
# to the deepest ancestor that EXISTS, resolve THAT physically, then re-attach
# the part that does not exist yet. This keeps `mkdir -p` semantics — naming a
# sample several directories deep still works — while resolving symlinks in
# whatever part of the path is real.
sample_probe=$SAMPLE
sample_tail=
while [ ! -e "$sample_probe" ]; do
    sample_tail="$(basename "$sample_probe")${sample_tail:+/$sample_tail}"
    sample_up=$(dirname "$sample_probe")
    [ "$sample_up" != "$sample_probe" ] || break
    sample_probe=$sample_up
done
sample_base=$(cd "$sample_probe" 2>/dev/null && pwd -P) || {
    echo "refusing: the sample path is not usable: $SAMPLE" >&2
    echo "          its nearest existing ancestor ($sample_probe) is not a directory" >&2
    exit 2; }
SAMPLE_ABS="$sample_base${sample_tail:+/$sample_tail}"

# The sample must sit OUTSIDE the library. A sample nested inside it gets
# indexed as part of the library on the next run, and every sampled photo
# then looks like a duplicate of itself. Checked BEFORE anything is created.
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

mkdir -p "$SAMPLE_ABS"

# ANY entry, not just regular files. `find -type f` neither counts nor descends
# a directory symlink, so a symlink pointing into the library passed this check
# and the mkdir/ln below then followed it and wrote there. Requiring a genuinely
# empty directory removes the whole class: with nothing already in it, there is
# no pre-existing link for the build to follow.
existing=$(find "$SAMPLE_ABS" -mindepth 1 | wc -l)
[ "$existing" -eq 0 ] || {
    echo "refusing: $SAMPLE_ABS already holds $existing item(s)" >&2
    echo "          a partial sample skews every count, and a symlink left in it" >&2
    echo "          can redirect the build into the library; clear it first" >&2
    exit 2 ; }

# Kept in step with RASTER_EXTENSIONS and RAW_EXTENSIONS in ns-engine.py: a
# sampler matching less than the engine supports hides whole formats from
# every validation run.
RASTER='jpg|jpeg|jpe|jfif|png|gif|bmp|webp|tif|tiff|heic|heif|avif'
RAW='raw|dng|cr2|cr3|crw|nef|nrw|arw|srf|sr2|raf|orf|rw2|pef|ptx|srw|erf|3fr|fff|iiq|mos|mrw|x3f'
PHOTO="\.($RASTER|$RAW)\$"
if [ "$ALL_TYPES" -eq 1 ]; then
    PATTERN="."
    WHAT="every file type (--all-types)"
elif [ "$INCLUDE_RAW" -eq 1 ]; then
    PATTERN="$PHOTO"
    WHAT="raster and RAW"
else
    PATTERN="\.($RASTER)\$"
    WHAT="raster only (--no-raw)"
fi

LIST=$(mktemp)
trap 'rm -f "$LIST"' EXIT

# Relative paths, so the sample reproduces the library's folder structure.
# Flattening instead would collide same-named photos from different albums.
cd "$LIB_ABS"

# A newline-delimited list cannot carry a name that itself contains a newline:
# the name is split across two lines, and the link loop then works on a
# truncated path, failing part-way and leaving a half-built sample. Detect it
# and refuse BEFORE creating anything, rather than aborting mid-build. Counting
# NUL-terminated records against lines is the cheap way to spot one.
nul_count=$(find . -type f -print0 | tr -dc '\0' | wc -c | tr -d ' ')
line_count=$(find . -type f | wc -l | tr -d ' ')
[ "$nul_count" = "$line_count" ] || {
    echo "refusing: a filename under $LIB_ABS contains a newline" >&2
    echo "          this sampler uses a line-oriented list, which cannot carry one;" >&2
    echo "          rename or exclude that file, then run again" >&2
    exit 2 ; }

find . -type f | grep -Ei "$PATTERN" | awk -v n="$NTH" '(NR - 1) % n == 0' > "$LIST" || true

count=0
while IFS= read -r rel; do
    mkdir -p "$SAMPLE_ABS/${rel%/*}"
    ln "$LIB_ABS/$rel" "$SAMPLE_ABS/$rel"
    count=$((count + 1))
done < "$LIST"

[ "$count" -gt 0 ] || {
    echo "no files matched under $LIB_ABS — nothing sampled" >&2; exit 1; }

# The deliberate duplicate is always of a PHOTO: a duplicate sidecar is excluded
# by file type and would exercise nothing.
first=$(grep -Ei "$PHOTO" "$LIST" | head -n 1 || true)
[ -n "$first" ] || { echo "no photos among the sampled files — nothing to duplicate" >&2; exit 1; }
ext=${first##*.}
ln "$SAMPLE_ABS/$first" "$SAMPLE_ABS/duplicate_of_first.$ext"

total=$(find "$SAMPLE_ABS" -type f | wc -l)
# Counted from the sampled list, not the finished directory: the duplicate
# link would otherwise be counted too, making "N of them RAW" a fraction of a
# different number than the one printed above it.
raws=$(grep -Eic "\.($RAW)\$" "$LIST" || true)
photos=$(grep -Eic "$PHOTO" "$LIST" || true)
echo "sampled   : $count file(s), $photos of them photos, 1 in $NTH matches under $LIB_ABS"
echo "formats   : $WHAT — $raws of the $photos photos are RAW"
echo "duplicate : duplicate_of_first.$ext — a second link to the first sampled photo"
echo "sample    : $total file(s), $(du -sh "$SAMPLE_ABS" 2>/dev/null | cut -f1) in $SAMPLE_ABS"
echo "library   : $(find "$LIB_ABS" -type f | wc -l) file(s), untouched"
echo
# "at least": this script plants ONE duplicate, but it cannot know how many the
# library already holds among the files it sampled. Stating an exact number
# invites reading a correct run as a wrong one — a real sample turned up five.
echo "Index and Copy should report $photos delivered and at least 1 skipped duplicate."
[ "$ALL_TYPES" -eq 0 ] || echo "Index should report $((count - photos)) file(s) excluded by file type, before hidden files are skipped."
