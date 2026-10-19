import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// In dev, /api goes to the results server (python -m backend.results_api).
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: { "/api": process.env.RESULTS_API_URL ?? "http://127.0.0.1:5001" },
  },
});
