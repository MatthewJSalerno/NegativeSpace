#!/usr/bin/env python3
"""Verify engine-spec.md 6.5 executes and matches what the engine actually creates.

That section calls itself the authoritative schema, "meant to be executed as
written". Nothing else keeps that true as the schema grows, so this check
executes it rather than trusting it. Compares in BOTH directions: a table in the engine and not the spec is
undocumented, and one in the spec and not the engine is fiction.

Exits non-zero on any difference, so it can gate a commit.
"""
from pathlib import Path
import pathlib
import re
import sqlite3
import sys
import tempfile

spec = Path("docs/engine-spec.md").read_text()
start = spec.index("### 6.5.")
end = spec.index("\n## 7.", start)
blocks = re.findall(r"```sql\n(.*?)```", spec[start:end], re.S)

con = sqlite3.connect(":memory:")
try:
    for b in blocks:
        con.executescript(b)
except sqlite3.Error as exc:
    print(f"spec block failed to execute: {exc}")
    sys.exit(1)

spec_tables = {r[0] for r in con.execute(
    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
spec_cols = {t: {r[1] for r in con.execute(f"PRAGMA table_info({t})")} for t in spec_tables}

sys.path.insert(0, ".")
import ns_db  # noqa: E402

with tempfile.TemporaryDirectory() as tmp:
    db = pathlib.Path(tmp) / "drift.db"
    ns_db.initialize(db)
    conn = ns_db.connect(db)
    real_tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
    real_cols = {t: {r[1] for r in conn.execute(f"PRAGMA table_info({t})")} for t in real_tables}
    conn.close()

# catalog_schema is written by initialize(), not part of the documented block.
undocumented = (real_tables - {"catalog_schema"}) - spec_tables
fictional = spec_tables - real_tables
errors = []
if undocumented:
    errors.append(f"in the engine, absent from 6.5: {sorted(undocumented)}")
if fictional:
    errors.append(f"in 6.5, absent from the engine: {sorted(fictional)}")
for t in sorted(spec_tables & real_tables):
    missing = real_cols[t] - spec_cols[t]
    extra = spec_cols[t] - real_cols[t]
    if missing:
        errors.append(f"{t}: columns in the engine, absent from 6.5: {sorted(missing)}")
    if extra:
        errors.append(f"{t}: columns in 6.5, absent from the engine: {sorted(extra)}")

print(f"Compared {len(real_tables)} engine tables against {len(spec_tables)} documented in 6.5.")
for e in errors:
    print(" ", e)
sys.exit(1 if errors else 0)
