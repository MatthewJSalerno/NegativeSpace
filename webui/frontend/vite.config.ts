import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The build lands in dist, which the web container serves (Dockerfile, nginx.conf).
// In development, `npm run dev` proxies the API to an app container on port 8000.
export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    proxy: { "/api": { target: "http://localhost:8000", ws: true } },
  },
});
