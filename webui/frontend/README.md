# Web interface screens

React + TypeScript, built with Vite. The Docker image builds them (the `frontend` stage
of the `Dockerfile`) and the API serves the result from `webui/static`, so nothing needs
installing on the host, and Node is not in the runtime image.

Check types and build without the image, in the same pinned Node image:

```bash
cd webui/frontend
docker run --rm --user $(id -u):$(id -g) -e HOME=/tmp -v "$PWD/..":/webui -w /webui/frontend \
  node:22-slim npm ci
docker run --rm --user $(id -u):$(id -g) -e HOME=/tmp -v "$PWD/..":/webui -w /webui/frontend \
  node:22-slim npm run build
```

`npm run dev` serves the screens with live reload and proxies `/api` to a server on
port 8080. The browser test (`tests/webui_browser_test.sh`) drives the built screens.

| File | Holds |
| --- | --- |
| `src/api.ts` | The API's response shapes and the fetch wrapper |
| `src/jobs.ts` | The live job feed and the words the drawer uses for counts and outcomes |
| `src/format.ts` | Sizes, counts, and date display rules (`webui-spec.md` §10) |
| `src/App.tsx` | First run, the library view, selection, confirmations |
| `src/components/` | Gallery, thumbnail, Inspector, job drawer, settings |
