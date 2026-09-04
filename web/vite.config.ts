import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, ".", "");
  const port = Number(env.DRIPCUT_WEB_PORT || 5173);
  const apiProxy = env.DRIPCUT_API_PROXY_URL || "http://127.0.0.1:8000";

  return {
    plugins: [react()],
    server: {
      port,
      strictPort: true,
      proxy: {
        "/api": apiProxy,
      },
    },
  };
});
