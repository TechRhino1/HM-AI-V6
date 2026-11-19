/// <reference types="vitest" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Built into the Python server's static dir so the dashboard runs without Node.
export default defineConfig({
  plugins: [react()],
  base: "/static/app/",
  build: {
    outDir: "../jarvis/ui/static/app",
    emptyOutDir: true,
    sourcemap: false,
    chunkSizeWarningLimit: 600,
  },
  server: {
    port: 5173,
    proxy: { "/api": "http://127.0.0.1:8501" },
  },
  test: { environment: "node" },
});
