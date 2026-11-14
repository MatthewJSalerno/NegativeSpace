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
