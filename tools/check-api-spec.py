#!/usr/bin/env python3
"""Fails when docs/api-spec.md and the API's routes disagree.

Every route the app registers under /api/v1 must have a heading in api-spec.md of the
form ### `METHOD /path`, and every such heading must be a route that exists. The
"Designed, not built" section is prose, not headings, so it is not checked. Run from
the repository root inside the image, which has FastAPI:

    docker run --rm -v "$PWD":/app -w /app negativespace python3 tools/check-api-spec.py
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from webui.app import create_app  # noqa: E402

HEADING = re.compile(r"^### `(GET|POST|PUT|PATCH|DELETE|WS) (/api/\S+)`\s*$", re.M)

# Route paths use {photo_id} / {run_id}; the document writes {id}. Compare shapes.
def shape(path: str) -> str:
    return re.sub(r"\{[^}]+\}", "{}", path)


routes = set()
for route in create_app().routes:
    if not route.path.startswith("/api/v1"):
        continue
    methods = getattr(route, "methods", None) or {"WS"}
    for method in methods - {"HEAD", "OPTIONS"}:
        routes.add((method, shape(route.path)))

text = Path("docs/api-spec.md").read_text()
documented = {(m, shape(p)) for m, p in HEADING.findall(text)}

missing = sorted(routes - documented)
stale = sorted(documented - routes)
for method, path in missing:
    print(f"docs/api-spec.md: {method} {path} is a route but has no heading")
for method, path in stale:
    print(f"docs/api-spec.md: {method} {path} is documented but no such route exists")
print(f"Checked {len(routes)} routes against {len(documented)} documented endpoints.")
sys.exit(1 if missing or stale else 0)
