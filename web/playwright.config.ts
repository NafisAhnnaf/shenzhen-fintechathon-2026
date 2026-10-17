import { defineConfig } from "@playwright/test";

// Runs against the API serving the built app on :8000 (NETWORK=localhost SIGNING=client), after /api/admin/reset.
export default defineConfig({
  testDir: "e2e",
  testIgnore: ["**/._*"],
  timeout: 90_000,
  workers: 1,
  use: { baseURL: process.env.BASE_URL ?? "http://127.0.0.1:8000", viewport: { width: 1440, height: 960 } },
  reporter: [["list"]],
});
