import { defineConfig } from "@playwright/test";

// README media: real screenshots and the live reader recording (see capture.spec.ts). Run against the API on :8000:
//   PW_CHANNEL=chrome npx playwright test -c media/media.config.ts
export default defineConfig({
  testDir: ".",
  testIgnore: ["**/._*"],
  timeout: 150_000,
  workers: 1,
  use: { channel: process.env.PW_CHANNEL, baseURL: process.env.BASE_URL ?? "http://127.0.0.1:8000", viewport: { width: 1440, height: 900 }, colorScheme: "light" },
  reporter: [["list"]],
});
