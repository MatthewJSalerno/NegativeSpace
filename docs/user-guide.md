# User guide

A first session with NegativeSpace, start to finish. The screenshots use NASA's public
image library. Screenshots show an earlier interface; navigation and setup details below
describe the current app.

> **Before you start:** NegativeSpace is not a backup of your photos. It backs up its
> catalog, never the photos themselves; keeping your own backups of your photos is your
> responsibility. See [If something goes wrong](recovery.md).

Install it first: the [README's quick start](../README.md#quick-start) takes four commands.

## 1. First start

Open **http://localhost:8080**. There is no catalog yet, so the page offers to create one,
then walks through the settings in five steps. They are starting values, and every
one can be changed later from the gear icon at the top right.

![Setup appearance choices (earlier interface)](images/welcome.png)

The **Appearance** step sets the palette and light/dark preference. **Files** chooses
file types, the earliest expected photo year, and when to be reminded to empty Rejects.
It also requires a choice to enable or disable small-image reminders; these never
restrict Copy or Move. **Backups** explains catalog backups, **Performance** sets how
many photos are read at once, and **Access** saves additional addresses used to open the app.

![The Files step: file types and the Rejects reminder](images/welcome-files.png)

## 2. Index: read your photos

The library starts empty. **Jobs** holds the jobs for the whole library; each item says
what it does, and why when it cannot run yet.

![The Jobs menu before anything is indexed](images/jobs-menu.png)

**Index** reads every photo in your source: its date, a checksum of its content, and a
small thumbnail. It moves and copies nothing, and never writes to your source. Its progress
shows at the top of the page; closing the browser does not stop it.

![An Index in progress](images/index-running.png)

## 3. Look around

When Index finishes, **Not organized** shows the source photos and an Index summary.
**Library**, **Needs review**, and **Rejects** remain empty until photos are organized.
The places are in the sidebar on the left. **Filters** beside the sort narrows by type,
**Folders** or **Dates**, and the box at the top searches by filename. After Copy or Move,
Library holds organized photos, Needs review filters those needing attention, and
Rejects holds photos you have rejected. Reason filters sit beneath these locations.

![The gallery, showing one year](images/gallery.png)

Click a photo to open it in the panel on the right: its file, its dates and where they came
from, and its history.

![A photo open in the panel](images/inspector.png)

## 4. Copy or Move

**Jobs › Copy** files every photo not yet organized into the destination's `library/`
folder, under `YYYY/MM/DD`, and never touches your source. **Move** does the same, then
removes each original once its copy is verified (it needs a writable source). Either can
take everything or one folder from Jobs. Tick photos instead and the bar at the top
offers what applies to them: Copy, Move, Reject, or Return to library. Each asks first.
A selection holds library photos or photos in Rejects, never both, so each action means
one thing. When a job finishes, you are where you were; **Show these photos** in its
banner shows what it did, and you can search and filter them like any other photos.

![Three photos selected: the bar offers Move and Reject](images/selection-bar.png)

![Copy finished](images/copy-finished.png)

Which to use is your choice. If you would rather not give any app write access to your
originals, use Copy only: the source stays read-only, you check the library your own way,
and you delete the originals yourself once you are confident. NegativeSpace never needs
to delete anything for its library to be complete.

## 5. Similar photos

**Has similar photos** lists organized Library photos with look-alikes; unorganized
source files are not compared in this view. Open one and choose **Similar
photos**: the counts show how many matches it has at each percentage. The percentage
measures visual similarity, not certainty; below 90%, matches are more likely to be
unrelated.

![A photo's similar photos](images/similar-photos.png)

Open a match to compare the two side by side: their size, format, dates and every
recorded detail. **Reject…** under a photo turns that one down; **Keep this one, reject
the other…** keeps one and reviews the rest before anything moves.

![Two look-alikes side by side](images/compare.png)

## 6. Reject what you do not want

**Reject…** moves a photo out of your library into a separate `rejects/` folder in your
destination. Nothing is deleted: the **Rejects** view shows what it holds, **Return to
library** brings a photo back, and you empty the folder yourself (**How to empty
Rejects** says how). A reminder appears on every page once Rejects grows past a size or
age you set in Settings.

If you Move, a rejected photo's original in your source is deleted too, once its copy in
Rejects is verified, so the source can end up empty. That copy is then the only one:
empty Rejects and the photo is gone. Every Move that includes rejected photos says so first.

![The Rejects view](images/rejects.png)

## 7. Check dates

**Suspicious dates** flags recorded years earlier than the minimum you chose in setup
(default 1800), or more than one year ahead of the current UTC year. Change the minimum
in **Settings › Files** to suit your collection. These are clues to investigate, not proof
of a wrong date; NegativeSpace changes no date by itself.

![Photos with suspicious dates](images/suspicious-dates.png)

## 8. History, logs and stats

Every photo keeps its full history: each file it has been, each copy made of it, and
every job that touched it. **View lineage tree** in the panel shows it.

![A photo's lineage](images/lineage.png)

**Logs** lists every job and everything it did, with any failures, their reasons, and
**Retry**.

![The log](images/logs.png)

**Stats**, under Logs in the sidebar, gives figures for the whole library.

![Stats](images/stats.png)

## 9. Settings

The gear icon opens Settings, in five tabs: **Appearance**, **Files**, **Backups** (with
the list of catalog backups and Back up now) **Performance**, and **Access**. Access saves the additional hostnames/IP addresses
you use to open the app. These settings survive replacing the photo catalog. Local
and Docker-configured addresses remain available for recovery.

![Settings](images/settings.png)

## Next

- Keep your own backups of your photos and of the destination.
- Point a gallery application such as Immich at the destination's `library/` folder, not
  the destination itself.
- [If something goes wrong](recovery.md) explains what can be recovered, and how.
