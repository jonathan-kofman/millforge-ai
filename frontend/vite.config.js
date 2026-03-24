import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig(({ command }) => ({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: command === "serve" ? {
      // Proxy API requests to the FastAPI backend during development only
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
    } : {},
  },
}));
