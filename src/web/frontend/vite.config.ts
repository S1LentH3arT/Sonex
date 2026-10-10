import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  clearScreen: false,
  envPrefix: ["VITE_"],
  build: { outDir: "../static", emptyOutDir: true },
  server: {
    proxy: {
      "/web/ws": {
        target: "ws://127.0.0.1:9002",
        ws: true,
        changeOrigin: true,
        rewriteWsOrigin: true,
      },
    },
  },
});
