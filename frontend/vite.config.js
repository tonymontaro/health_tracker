import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
export default defineConfig({
    plugins: [react()],
    server: {
        port: 5173,
        allowedHosts: ["health.anthonyngene.com"],
        proxy: {
            "/api": "http://localhost:8001",
            "/health": "http://localhost:8001",
        },
    },
});
