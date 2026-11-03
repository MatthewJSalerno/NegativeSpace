# Instructions for coding assistants

These instructions apply throughout this repository.

## UI design is a shared contract

Before changing UI components, CSS, user-facing messages, or interaction behavior,
read [docs/ui-design.md](docs/ui-design.md). It is the authoritative design standard,
not an optional example. Read the relevant behavior in
[docs/webui-spec.md](docs/webui-spec.md) as well.

- Reuse the existing design tokens and shared controls. Follow the documented text
  roles, spacing, colors, and control states; do not invent a separate style for a
  new screen.
- Fix shared styling at its source. Check other consumers of the same rule instead
  of adding a local override that leaves the inconsistency elsewhere.
- Keep adjacent links and text buttons consistent in size, line height, and
  alignment. Preserve intentional differences between headings, body text, and
  supporting details.
- Warnings that require user action need a working resolution path. Explain what
  is affected and provide the action or a direct route to the affected items. Do
  not suggest a retry that cannot fix the condition. Unbuilt recovery flows belong
  in [TODO.md](TODO.md), explicitly identified as unfinished.
- Verify appearance in the rendered app, including affected dialogs, compact text,
  and desktop zoom or narrow reflow. Use relevant existing browser checks from
  [tests/README.md](tests/README.md); a successful build alone does not establish
  visual consistency.
- When the user changes an established design decision, update the design standard
  alongside the implementation so future work follows the same decision. Keep the
  detailed rules in that document rather than copying them into agent-specific files.

## User documentation is a shared contract

Before changing README.md, docs/install.md, docs/user-guide.md or docs/recovery.md, read
[docs/user-docs-standard.md](docs/user-docs-standard.md): who each document is for, voice,
wording, safety claims and screenshots. Record a changed decision there, not in
agent-specific files.

## Maintainer validation

When requesting manual checks, follow the [validation instructions](docs/manual-validation.md#maintainer-validation-rules).
Provide numbered tests, lettered steps and verified searchable filenames for photo-specific
checks. Do not make the maintainer find a suitable photo or infer it from a source path.
Keep manual steps and reported results in docs/manual-validation.md; link there from other
documents instead of creating another checklist.

## Code layout

The engine is the `engine/` package (run as `python -m engine`); the API is `webui/`; the
screens are `webui/frontend/src` (`App.tsx` is the page shell, each page in `components/`).
In both Python packages, a module calls another module's functions, and reads anything
rebound at runtime, as `module.name`, never through `from module import name`: one binding
per name, so a test that replaces a function replaces it for every caller. Constants and
classes (`PhotoStatus`, `Config`) may be imported by name. `engine/__init__.py` lists the engine's modules by area.
Browser tests are in `tests/browser/`, the other suites in `tests/`, tools and the sample
library builders in `tools/`.

## This machine

Before creating folders, mounting volumes or starting containers, read
`private/environment-private.md` in the maintainer's main working folder (git-ignored, so a
clone has no copy): where to write, the sample photos to use, and what never to touch.
Its paths never go into this repository.

## Evidence, not assumptions

Every claim in code comments, specs, docs, commits, PRs and messages to the maintainer
rests on evidence of one of four kinds. Say which:

- **Verified:** you ran it, measured it or reproduced it; say how (the test that
  passes, the command, the screenshot you inspected).
- **Read:** you read the code or document; give `file:line`.
- **Sourced:** a fact about the outside world (another application's behaviour, a file
  format, a tool's capabilities, a standard) from a primary source you opened in this
  session: the vendor's documentation, the tool's README or code, or the standard.
  Link it and quote the line you rely on. Carry its caveats (limits, maintenance status)
  into anything users will read.
- **Assumed:** anything else. An assumption may not drive a design or code change;
  resolve it first or ask the maintainer.

Rules that follow:

- "Should work", "likely" and "probably" are not results. Before saying something works,
  show it working; before saying a bug is fixed, show the test failing on the old code
  and passing on the new.
- Do not infer behaviour from names, comments or docs; follow the code path. Where code
  and docs disagree, report it rather than picking one.
- When a requirement is unclear, contradictory or undecided, stop and ask, with the
  options and a recommendation. Do not choose silently, and do not resolve a conflict
  between an approved decision and its tests by changing either on your own.
- When no primary source exists, say so and propose how to check (for example a
  generated fixture), rather than filling the gap from memory.
- End each report with **Limits**: what you did not check, run or measure.

## Repository context and privacy

Component specifications start at [docs/project-spec.md](docs/project-spec.md).
Validation against a real library must not publish personal filenames, directory
names, machine details, or raw run output in repository files or commit/PR text.
Use generated fixtures and aggregate validation results.

Code reviews and audits follow `private/ai-reviews/review-process.md` (git-ignored): documents are
named and logged there, and never committed to this repository; a pull request description
carries the summary.
