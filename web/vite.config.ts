import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The API runs on :8000 (uvicorn apagent.api:app). In development Vite proxies /api to it.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { "/api": "http://127.0.0.1:8000" },
    watch: { ignored: ["**/._*"] },
  },
  build: { outDir: "dist", chunkSizeWarningLimit: 2000 },
});
