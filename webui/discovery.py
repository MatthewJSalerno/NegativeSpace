"""Display a recorded walk without enumerating the source or querying each photo."""
from engine import ns_db

# File-type accounting describes extensions, not validation of their contents.
# Generic JSON is deliberately Other: its suffix cannot establish an export sidecar.
SIDECAR_EXTENSIONS = frozenset({'.xmp', '.aae', '.thm'})
VIDEO_EXTENSIONS = frozenset({'.mov', '.mp4', '.m4v', '.avi', '.mkv', '.mts', '.m2ts', '.mpg', '.mpeg', '.3gp', '.webm', '.wmv'})


def breakdown(conn, run_id):
    recorded = ns_db.read_discovery(conn, run_id)
    if recorded is None:
        return None
    excluded = recorded['excluded_by_extension']
    disabled = {ext: n for ext, n in excluded.items() if ext in ns_db.SUPPORTED_EXTENSIONS}
    sidecars = sum(n for ext, n in excluded.items() if ext in SIDECAR_EXTENSIONS)
    videos = sum(n for ext, n in excluded.items() if ext in VIDEO_EXTENSIONS)
    return {'files_found': recorded['files_found'], 'eligible': recorded['eligible'],
            'photos': recorded['eligible_by_extension'], 'disabled_photos': disabled,
            'sidecars': sidecars, 'videos': videos,
            'other': recorded['excluded'] - sum(disabled.values()) - sidecars - videos,
            'partial': recorded['partial'], 'unreadable': recorded['unreadable']}
