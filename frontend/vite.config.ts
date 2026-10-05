import path from "node:path";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const backend = process.env.OFFLINER_BACKEND ?? "http://127.0.0.1:8080";

export default defineConfig({
  plugins: [react()],
  resolve: { alias: { "@": path.resolve(__dirname, "./src") } },
  server: {
    port: 5173,
    proxy: {
      "/api": { target: backend, changeOrigin: true, ws: true },
    },
  },
});
