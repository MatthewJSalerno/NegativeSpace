# User documentation standard

How the user-facing documents are written: [README.md](../README.md),
[install.md](install.md), [user-guide.md](user-guide.md) and [recovery.md](recovery.md).
The specifications are written for developers and are not covered here. This is the
documentation counterpart of [ui-design.md](ui-design.md): follow it for every change to
these files, and record a changed decision here rather than in an agent's own notes.

## Who each document is for

| Document | Reader | Holds |
| --- | --- | --- |
| README | Someone deciding whether to install, then installing | What it does, why the photos are safe, a quick install, the four folders, five getting-started steps, network exposure, what it doesn't do, links |
| install.md | Whoever runs the containers | Each folder in detail, user and time zone, network access, network shares, stopping jobs, file types, catalog versions, writing your own compose file |
| user-guide.md | Someone using the web interface | How your photos are protected, then each step of the workflow in the order it is done |
| recovery.md | Someone whose setup has gone wrong | What can be recovered, and how |

**Keep the README lean,** following GitHub's
[About READMEs](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/about-readmes)
and [Standard Readme](https://github.com/RichardLitt/standard-readme). Detail goes to
install.md or the guide, with a link. The README's "What it doesn't do" is the short form
of `webui-spec.md` §8; change both together.

**No command-line flags, database terms or internal names** in these documents. End users
work through the web interface; the engine's command line is in
[engine-cli.md](engine-cli.md) and its internals in the specifications.

## Voice

- Second person, present tense: "**Copy** files every photo…", not "the user can copy".
- Calm and plain. Explain, don't sell. No absolute claims such as "every precaution
  possible"; say what it does and, where it matters, what it can't do.
- **Explain why rather than give orders.** "`library/` is laid out for your gallery app to
  read; `rejects/` sits beside it, so photos you turn down stay out of your gallery" rather
  than "point your gallery at `library/`, not the destination".
- Describe what is true now. No "new", "now", "earlier interface" or version history (that
  is the CHANGELOG), and no planned features beyond the README's short "Not yet" list.
- Platforms: say what is tested ("tested on Linux"), not what is required. On Mac or
  Windows, name [Rancher Desktop](https://rancherdesktop.io/) (open source, container
  engine set to dockerd) and say it is untested.

## Words

- **Copy and Move are only ever the actions.** The result is "the photo in your library"
  (or "the new file"), never "the copy", so the button and the file are not confused.
- Names on screen are **bold** and spelled exactly as shown, ellipsis included:
  **Reject…**, **Copy all photos…**. Menus and settings use ›: **Jobs › Copy**,
  **Settings › Files**.
- Places keep their sidebar names: **Not organized**, **Library**, **Needs review**,
  **Rejects**; never "the gallery" or "the inbox".
- "Select", never "tick". A step the user takes is a button that does it, not a manual
  workaround.

## Claims about safety

Every statement about what protects the user's files is checked against
[engine-spec.md](engine-spec.md) before it is published, and changed when the behaviour
changes. Current claims and their sources:

| Claim | Source |
| --- | --- |
| Index and Copy never write to the source | engine-spec §4.1 |
| Every photo is verified in the library before Move deletes its original | engine-spec §4.2, Copy-Verify-Delete |
| Existing files are never replaced; a taken name gets a numbered suffix | engine-spec §4.2, Unique Filename Enforcement |
| The app container runs as `PUID`/`PGID`; neither container is privileged | `docker/entrypoint.sh`, `docker/compose.yml` |

Do not claim the containers never run as root: the app container's entrypoint starts as
root to set folder ownership before dropping to `PUID`/`PGID`, and the web container uses
the stock nginx image.

## User guide sections

One section per step of the workflow, in the order it is done. Each section says what it
is for in one sentence, what to click and what happens, the safety point in one line where
it matters, and shows at most one screenshot. Link to the specifications for detail
instead of copying it.

## Screenshots

- Dark mode, 1440 × 900, from the public NASA demo set only; never anything from a real
  library.
- Every screenshot matches the current app. A stale one is retaken or removed, never
  captioned as old.
- Name a file after what it shows (`library.png`). When a screenshot's content changes
  substantially, give it a new name: browsers and GitHub cache images by address.

## Keeping these documents current

- A pull request that changes what the user sees updates the matching guide text in the
  same pull request.
- Restructuring and screenshot refreshes go through small documentation pull requests,
  merged often so feature branches rebase onto them with few conflicts.
- Before merging, check that every link and `#anchor` in these files resolves, and run the
  repository's documentation checks (`tools/check-specs.py`).
