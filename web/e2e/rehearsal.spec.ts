import { expect, test, type Page } from "@playwright/test";

// The live demo in docs/speech.md, step by step (section 0 setup, then B1-B6). Uses one vision-model read.
// Run only when rehearsing: PW_CHANNEL=chrome npx playwright test e2e/rehearsal.spec.ts
test.skip(!process.env.REHEARSAL, "set REHEARSAL=1 to run the demo rehearsal");

async function signIn(page: Page, who: "Owner" | "Finance manager") {
  await page.context().clearCookies();
  await page.goto("/login");
  await page.getByRole("radio", { name: new RegExp(`^${who}`) }).click();
  await page.getByRole("button", { name: "Local test key" }).click();
  await page.waitForURL("**/desk", { timeout: 20_000 });
}

test("demo rehearsal", async ({ page }) => {
  test.setTimeout(240_000);
  // 0. Setup: reset as the owner, skip the payee cool-down.
  await signIn(page, "Owner");
  await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Settings" }).click();
  await page.getByRole("button", { name: "Reset the demo" }).click();
  await page.getByRole("button", { name: "Yes, reset" }).click();
  await expect(page.getByText(/Fresh contracts deployed/)).toBeVisible({ timeout: 60_000 });
  await page.getByRole("button", { name: "Skip 5 minutes" }).click();
  await page.waitForTimeout(1500);

  // B1. Routine bill.
  await signIn(page, "Finance manager");
  await page.getByRole("button", { name: /Kai Tak Fasteners Ltd.*1,810\.16/ }).click();
  await expect(page.getByText("Paid by the agent on its own.")).toBeVisible({ timeout: 30_000 });

  // B2. Live reader on the poisoned PDF.
  await page.locator("input[type=file]").first().setInputFiles("../data/demo/documents/t07_poisoned.pdf");
  await expect(page.getByText("SYSTEM NOTE TO AI ASSISTANT", { exact: false }).first()).toBeVisible({ timeout: 90_000 });
  await expect(page.getByText(/payee frozen/).first()).toBeVisible({ timeout: 30_000 });
  await page.getByRole("button", { name: "Open the bill" }).click();

  // B3. Padded bill: manager signs, owner co-signs.
  await page.getByRole("button", { name: /Acme Metals.*53,800\.12/ }).click();
  await expect(page.getByText(/The price is up \+9\.0%/)).toBeVisible({ timeout: 30_000 });
  await page.getByRole("button", { name: /Sign and pay \$49,639\.64/ }).click();
  await expect(page.getByText(/the owner signs too/).first()).toBeVisible({ timeout: 30_000 });
  await signIn(page, "Owner");
  await page.locator(".qcol .card").first().getByRole("button", { name: /Acme Metals/ }).click();
  await page.getByRole("button", { name: /Sign as owner and pay \$49,639\.64/ }).click();
  await expect(page.getByText("Paid after the finance manager signed.")).toBeVisible({ timeout: 30_000 });

  // B4. Refusal.
  await page.getByRole("button", { name: "Add a new bank account for Acme" }).click();
  await page.getByRole("button", { name: "Plan", exact: true }).click();
  await expect(page.getByText(/can't|cannot|not something/i).first()).toBeVisible({ timeout: 20_000 });

  // B5. Pause and resume.
  await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Security" }).click();
  await expect(page.getByText("Tsuen Wan Aluminium Works").first()).toBeVisible();
  await page.getByRole("button", { name: "Pause the agent" }).click();
  await expect(page.getByText("The agent is paused.").first()).toBeVisible({ timeout: 15_000 });
  await page.getByRole("button", { name: "Resume" }).click();
  await expect(page.getByText("The agent is running.")).toBeVisible({ timeout: 30_000 });

  // B6. Risk, Activity, More → Payments.
  await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Risk" }).click();
  await expect(page.getByText("How much the agent may pay on its own")).toBeVisible();
  await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Activity" }).click();
  await expect(page.getByText(/So far the agent has/)).toBeVisible();
  await page.getByRole("button", { name: /More/ }).click();
  await page.getByRole("menuitem", { name: "Payments" }).click();
  await expect(page.getByRole("heading", { name: "Payments" })).toBeVisible();
});
