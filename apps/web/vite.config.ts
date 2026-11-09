import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Same-origin proxy only. No keys, runner routes or arbitrary target from the browser.
const api = process.env.ED_API_PROXY ?? "http://127.0.0.1:8000";
const url = new URL(api);
if (
  !["127.0.0.1", "localhost"].includes(url.hostname) ||
  url.protocol !== "http:"
) {
  throw new Error("Development API proxy must be loopback HTTP");
}
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": { target: api, changeOrigin: false },
      "/health": { target: api, changeOrigin: false },
    },
  },
  preview: {
    proxy: {
      "/api": { target: api, changeOrigin: false },
      "/health": { target: api, changeOrigin: false },
    },
  },
});
