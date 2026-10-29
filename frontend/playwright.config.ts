import { defineConfig, devices } from "@playwright/test";

const PORT = 3100;

export default defineConfig({
  testDir: "tests/e2e",
  use: {
    baseURL: `http://localhost:${PORT}`,
    // Pinned so times on the page are the same on every machine.
    timezoneId: "America/Los_Angeles",
  },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"] } },
    { name: "mobile", use: { ...devices["Pixel 7"] } },
  ],
  webServer: {
    command: `npx next dev -p ${PORT}`,
    url: `http://localhost:${PORT}`,
    // Always test on sample data, so `?scenario=` works even when .env.local points at an API.
    env: { NEXT_PUBLIC_ECOSHIFT_API_URL: "" },
    reuseExistingServer: !process.env.CI,
  },
});
