import { expect, test } from "@playwright/test";

// These run against the built-in sample data (no NEXT_PUBLIC_ECOSHIFT_API_URL), so values are
// deterministic per hour but not hard-coded here; assertions check structure and behaviour.

test.describe("landing page", () => {
  test("leads with the live forecast and links to the dashboard", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Run heavy jobs when power is cheapest.");
    await expect(page.getByTestId("hero-headline")).toContainText(/cheapest/);
    await expect(page.getByText("Sample data").first()).toBeVisible();
    // The CLI demo prints the same forecast as the hero card.
    const best = (await page.getByTestId("hero-headline").textContent()) ?? "";
    const saved = best.match(/(\$[\d.,]+)\s*less than starting now/)?.[1];
    if (saved) await expect(page.getByTestId("cli-output")).toContainText(`saves ${saved} vs running now`);
    await page.getByRole("link", { name: "Open the dashboard" }).click();
    await expect(page).toHaveURL(/\/dashboard$/);
  });
});

test.describe("dashboard", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/dashboard");
    await expect(page.getByTestId("now-price")).toBeVisible();
  });

  test("shows the verdict, the chart, and the top 3 windows", async ({ page }) => {
    await expect(page.getByText("Sample data")).toBeVisible();
    await expect(page.getByText(/^Updated /)).toBeVisible();
    await expect(page.getByRole("slider", { name: "Job start time" })).toBeVisible();
    const windows = page.getByRole("list", { name: "Best start times" }).getByRole("button");
    await expect(windows).toHaveCount(3);
    // The job starts on the best window.
    await expect(windows.first()).toHaveAttribute("aria-pressed", "true");
  });

  test("changing the job length re-ranks windows and updates the CLI command", async ({ page }) => {
    await page.getByRole("button", { name: "2h", exact: true }).click();
    await expect(page.getByTestId("job-readout")).toContainText("Your 2h job");
    await expect(page.getByText("carbon-windows best --duration 2 --location fresno-305-west-napa-avenue")).toBeVisible();
  });

  test("the job block moves with the keyboard and reports the change", async ({ page }) => {
    const slider = page.getByRole("slider", { name: "Job start time" });
    const before = Number(await slider.getAttribute("aria-valuenow"));
    const readout = await page.getByTestId("job-readout").textContent();
    await slider.focus();
    await page.keyboard.press(before > 0 ? "ArrowLeft" : "ArrowRight");
    await expect(slider).toHaveAttribute("aria-valuenow", String(before > 0 ? before - 1 : before + 1));
    await expect(page.getByTestId("job-readout")).not.toHaveText(readout ?? "");
  });

  test("picking a window moves the job there", async ({ page }) => {
    const second = page.getByRole("list", { name: "Best start times" }).getByRole("button").nth(1);
    await second.click();
    await expect(second).toHaveAttribute("aria-pressed", "true");
  });

  test("the table view lists every hour", async ({ page }) => {
    await page.getByRole("button", { name: "Table" }).click();
    const forecast = page.getByRole("table", { name: "Hourly day-ahead price forecast and cheapest windows" });
    await expect(forecast.locator("tbody tr")).toHaveCount(72);
  });

  test("switching campus reloads the forecast", async ({ page }) => {
    await page.getByLabel("Datacenter campus").selectOption("san-jose-sample-campus");
    await expect(page.getByText("Right now in San Jose")).toBeVisible();
    await expect(page.getByText("carbon-windows best --duration 4 --location san-jose-sample-campus")).toBeVisible();
  });

  test("the power draw changes the dollar figures and the CLI command", async ({ page }) => {
    const before = await page.getByTestId("job-readout").textContent();
    await page.getByLabel("Average power draw in kilowatts").fill("80");
    await expect(page.getByTestId("job-readout")).not.toHaveText(before ?? "");
    await expect(page.getByText(/carbon-windows best --duration 4 --kw 80 --location /)).toBeVisible();
  });

  test("a deadline preset re-ranks windows and adds the deadline to the CLI command", async ({ page }) => {
    await page.getByRole("button", { name: "Tomorrow 9 AM" }).click();
    await expect(page.getByRole("button", { name: "Tomorrow 9 AM" })).toHaveAttribute("aria-pressed", "true");
    await expect(page.getByText(/carbon-windows best --duration 4 --deadline \S+T09:00-0[78]:00 --location fresno-305-west-napa-avenue/)).toBeVisible();
    await page.getByRole("button", { name: "Any time" }).click();
    await expect(page.getByText("carbon-windows best --duration 4 --location fresno-305-west-napa-avenue")).toBeVisible();
  });

  test("the now card shows what the savings compare against", async ({ page }) => {
    await expect(page.getByText("Start now", { exact: true })).toBeVisible();
    await expect(page.getByText("Best window", { exact: true })).toBeVisible();
  });

  test("a deadline too soon for the job says so", async ({ page }) => {
    await page.getByRole("button", { name: "Custom" }).click();
    const deadline = page.getByLabel("Custom deadline");
    // Two hours before the earliest deadline that fits a 4h job.
    const tooSoon = await deadline.evaluate((input: HTMLInputElement) => {
      const earliest = new Date(input.min);
      earliest.setHours(earliest.getHours() - 2);
      const pad = (n: number) => String(n).padStart(2, "0");
      return `${earliest.getFullYear()}-${pad(earliest.getMonth() + 1)}-${pad(earliest.getDate())}T${pad(earliest.getHours())}:00`;
    });
    await deadline.fill(tooSoon);
    await expect(page.getByText("No 4h window fits before the deadline.")).toBeVisible();
    await expect(page.getByText("Deadline too soon")).toBeVisible();
  });
});

test.describe("dashboard states", () => {
  test("a stale forecast is flagged", async ({ page }) => {
    await page.goto("/dashboard?scenario=stale");
    await expect(page.getByText("This forecast is out of date.")).toBeVisible();
    await expect(page.getByText(/^Stale · updated/)).toBeVisible();
  });

  test("an API failure shows a retry", async ({ page }) => {
    await page.goto("/dashboard?scenario=error");
    // Filter by text: Next.js adds its own empty role="alert" route announcer.
    await expect(page.getByRole("alert").filter({ hasText: "Couldn't load the forecast" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Try again" })).toBeVisible();
  });
});

for (const [path, readyTestId] of [
  ["/", "hero-headline"],
  ["/dashboard", "now-price"],
]) {
  test(`${path} never scrolls sideways`, async ({ page }) => {
    await page.goto(path);
    await expect(page.getByTestId(readyTestId)).toBeVisible();
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(overflow).toBe(0);
  });
}
