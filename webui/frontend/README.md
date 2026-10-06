# Web interface screens

React + TypeScript, built with Vite. `docker/web.Dockerfile` builds them with Node and
serves the result with nginx (`docker/nginx.conf`), which also passes `/api` to the app
container. That is the `web` service in `docker/compose.yml`. Nothing needs installing
on the host.

Check types and build without the image, in the same pinned Node image:

```bash
cd webui/frontend
docker run --rm --user $(id -u):$(id -g) -e HOME=/tmp -v "$PWD/..":/webui -w /webui/frontend \
  node:22-slim npm ci
docker run --rm --user $(id -u):$(id -g) -e HOME=/tmp -v "$PWD/..":/webui -w /webui/frontend \
  node:22-slim npm run build
```

`npm run dev` serves the screens with live reload and proxies `/api` to an app container
listening on port 8000. The browser test (`tests/browser/webui_browser_test.sh`) drives the built screens.

| File | Holds |
| --- | --- |
| `src/api.ts` | The API's response shapes and the fetch wrapper |
| `src/jobs.ts` | The live job feed and the words the drawer uses for counts and outcomes |
| `src/format.ts` | Sizes, counts, and date display rules (`webui-spec.md` §10) |
| `src/nav.ts` | Moving between pages without reloading; the address bar is the source of truth |
| `src/paged.ts` | Continuous scrolling with stable photo identities and page jumps |
| `src/appearance.ts` | The colour palette, remembered per browser |
| `src/comparisonState.ts` | The comparison workspace's state in the address |
| `src/rejecting.ts` | Rejecting and returning single photos from the similarity screens |
| `src/App.tsx` | The page shell: first run, a catalog problem or setup, then the page the address names |
| `src/components/LibraryPage.tsx` | The Library: views, filters, selection, reviews and the jobs started there |
| `src/components/FirstRun.tsx` | Creating a catalog, and a catalog that cannot be opened |
| `src/components/` | The other screens: gallery, Inspector, comparison, logs, stats, settings, dialogs |
| `src/components/ui/` | Shared controls: Modal, Field, MenuButton, SearchField, Tabs, Workspace |
