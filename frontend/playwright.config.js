import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests/browser",
  timeout: 20000,
  workers: 2,
  use: { baseURL: "http://127.0.0.1:43017", trace: "retain-on-failure" },
  webServer: {
    command: "npm run dev -- --host 127.0.0.1 --port 43017 --strictPort",
    url: "http://127.0.0.1:43017",
    reuseExistingServer: false,
  },
});
