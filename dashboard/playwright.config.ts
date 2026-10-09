import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  workers: 1,
  timeout: 30000,
  use: {
    baseURL: "http://127.0.0.1:3100",
    launchOptions: {
      executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE || undefined,
      args: ["--no-sandbox", "--disable-dev-shm-usage"],
    },
  },
  webServer: [
    {
      command: `"${process.env.AURA_TEST_PYTHON || "python"}" -m aura.webapp.server_v3 --port 8766`,
      cwd: "..",
      url: "http://127.0.0.1:8766/api/health",
      reuseExistingServer: false,
      timeout: 30000,
    },
    {
      command: "npm run start",
      url: "http://127.0.0.1:3100",
      reuseExistingServer: false,
      timeout: 30000,
    },
  ],
});
