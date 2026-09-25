import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The build lands in webui/static, which the API serves (webui/app.py). In
// development, `npm run dev` proxies the API to a server on port 8080.
export default defineConfig({
  plugins: [react()],
  build: { outDir: "../static", emptyOutDir: true },
  server: {
    host: true,
    proxy: { "/api": { target: "http://localhost:8080", ws: true } },
  },
});
