# NegativeSpace

A photo-organizing engine with a web UI. The rules shared by every coding assistant are in
AGENTS.md, imported here so they are always loaded; this file adds only what they do not say.

@AGENTS.md

## Where things are

Two containers (`docker/compose.yml`), both images built from the repository root with the
Docker files in `docker/`:

- `app`: the engine and the FastAPI layer that runs it (`webui/app.py`, `catalog.py`,
  `jobs.py`).
- `web`: nginx serving the React + TypeScript screens (`webui/frontend`) and passing `/api`
  to `app`.

The API starts the engine with CLI arguments. Those stay documented and usable, but end
users work only through the web UI.

Specifications are organized by component, not by release phase:

| Document | Covers |
| --- | --- |
| `docs/project-spec.md` | Scope and status |
| `docs/engine-spec.md` | The engine |
| `docs/webui-spec.md` | The web interface |
| `docs/api-spec.md` | The web API as built; `tools/check-api-spec.py` fails CI when a route is missing from it |
| `docs/ui-design.md` | Appearance and interaction; read it before any UI work and record design decisions there |

How to run each test suite is in `tests/README.md`.

## Privacy: never publish library contents

The maintainer validates against a real photo library. Its directory names and filenames
contain personal information: family names, event names, locations, dates.

Never put any of these into a commit message, PR title or body, issue, code comment, test
fixture or any other file in this repository:

- Absolute paths from a real run (`/nfs/...`, `/data/source/...`, `/home/<user>/...`).
- Directory or file names seen in the library, including partial ones.
- Hostnames, usernames or mount points from the maintainer's machines.
- Verbatim log output or SQL query results from a run against the real library.

Aggregate figures are safe and are what make a validation record useful: file counts, byte
totals, throughput, wall-clock times, per-status counts, schema versions. To refer to one
file or directory, describe its shape ("a single leaf directory of ~1,300 files from a
bulk-download export"), never its path.

Run output the maintainer pastes into a conversation is reference material for that
conversation only. Summarize it as numbers before any of it goes into the repository.

## Validation records

The maintainer validates a branch against the real library before it merges. Record the
results in the PR body as a table of counts, sizes, rates and wall-clock times, so the
evidence outlives the terminal scrollback. Never paste the raw run log.
