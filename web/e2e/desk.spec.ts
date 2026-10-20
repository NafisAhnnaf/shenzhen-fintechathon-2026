import { expect, test, type Page } from "@playwright/test";

// Runs against the API serving the built app on :8000 (NETWORK=localhost SIGNING=client GOVERNOR_URL=...), with a
// local Hardhat node. The first test resets the demo. Each person signs in with their own local test wallet.
const SHOTS = process.env.SHOTS ?? "/tmp/shots";
type Who = "owner" | "finance manager" | "bank" | "arbiter";

async function signIn(page: Page, who: Who) {
  await page.context().clearCookies();
  await page.goto("/login");
  await page.evaluate(() => localStorage.clear());
  await page.goto("/login");
  const other = page.getByRole("button", { name: "Use another wallet" });
  if (await other.isVisible().catch(() => false)) await other.click();
  await page.getByRole("button", { name: `Local test account: ${who}` }).click();
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.waitForURL("**/bills", { timeout: 20_000 });
}

async function processDoc(page: Page, invNo: string) {
  await page.goto("/inbox");
  const row = page.getByRole("row").filter({ hasText: invNo }).first();
  await row.getByRole("button", { name: "Process" }).click();
  await page.waitForURL("**/bills?bill=*", { timeout: 30_000 });
}

test.describe.serial("payables desk", () => {
  test("owner resets the demo; a routine bill is paid by the agent", async ({ page }) => {
    await signIn(page, "owner");
    expect((await page.request.post("/api/admin/reset")).ok()).toBeTruthy();
    await processDoc(page, "KAI-2512001");
    const detail = page.locator(".detail");
    await expect(detail.getByText("Paid", { exact: true }).first()).toBeVisible();
    await expect(detail.locator(".by.agent")).toBeVisible();
    await expect(detail.getByText("Invoice vs order vs goods received")).toBeVisible();
    await page.screenshot({ path: `${SHOTS}/01-paid-by-agent.png`, fullPage: true });
  });

  test("price above market: query sent by the agent, manager signs, owner co-signs above $25,000", async ({ page }) => {
    await signIn(page, "finance manager");
    await processDoc(page, "ACM-2512412");
    const d = page.locator(".detail");
    await expect(d.getByText(/Market check/)).toBeVisible();
    await expect(d.getByText(/Q-001: invoice ACM-2512412/)).toBeVisible();
    await page.screenshot({ path: `${SHOTS}/02-market-check.png`, fullPage: true });
    await d.getByRole("button", { name: "Approve and sign" }).click();
    await expect(page.getByText(/the owner signs too/).first()).toBeVisible({ timeout: 30_000 });

    await signIn(page, "owner");
    await page.goto("/approvals");
    await page.getByRole("button", { name: /Sign as owner/ }).click();
    await expect(page.locator(".detail .by")).toContainText("Finance manager", { timeout: 30_000 });
    await expect(page.locator(".detail").getByText("Paid", { exact: true }).first()).toBeVisible();
  });

  test("request in plain words: one question, a plan, run", async ({ page }) => {
    await signIn(page, "owner");
    for (const k of ["t19_acme_0", "t19_acme_1"]) await page.request.post(`/api/inbox/documents/${k}?process=false`);
    await page.getByLabel("Ask the agent").fill("Pay the copper supplier");
    await page.getByLabel("Ask the agent").press("Enter");
    await expect(page.getByText("Which supplier?")).toBeVisible({ timeout: 20_000 });
    await page.getByRole("button", { name: "Acme Metals (HK) Ltd", exact: true }).click();
    await page.getByRole("button", { name: "Run", exact: true }).click();
    await expect(page.locator(".popover").getByText("Done.")).toBeVisible({ timeout: 40_000 });
    await page.screenshot({ path: `${SHOTS}/03-plan-done.png` });
  });

  test("payments register: who paid, by period, verified on-chain", async ({ page }) => {
    await signIn(page, "owner");
    await page.request.post("/api/anchor");
    await page.goto("/payments");
    await page.getByRole("button", { name: "Agent", exact: true }).click();
    await expect(page.getByRole("row").filter({ hasText: "KAI-2512001" })).toBeVisible();
    await page.getByRole("button", { name: "Finance manager", exact: true }).click();
    await expect(page.getByRole("row").filter({ hasText: "ACM-2512412" })).toBeVisible();
    await page.getByRole("row").filter({ hasText: "ACM-2512412" }).getByRole("button", { name: "Verify" }).click();
    await expect(page.getByText("This line is in the root stored on-chain.")).toBeVisible({ timeout: 20_000 });
    await page.screenshot({ path: `${SHOTS}/04-verified.png` });
    await page.getByRole("button", { name: "Close" }).click();
    await page.locator("#period").selectOption("lastmonth");
    await page.getByRole("button", { name: "All", exact: true }).click();
    await expect(page.getByText(/Before the agent \(ERP\)/).first()).toBeVisible();
  });

  test("controls: a poisoned invoice is held and shows in the security events", async ({ page }) => {
    await signIn(page, "owner");
    await processDoc(page, "TSU-2512019");
    await page.goto("/controls");
    await expect(page.getByRole("heading", { name: "Security events" })).toBeVisible();
    await expect(page.getByRole("cell", { name: "Frozen" }).first()).toBeVisible({ timeout: 15_000 });
    await expect(page.getByRole("cell", { name: "To a person" }).first()).toBeVisible();
    await page.screenshot({ path: `${SHOTS}/05-controls.png`, fullPage: true });
  });

  test("missed credit: manager confirms, bank disputes, arbiter decides, claim paid", async ({ page }) => {
    await signIn(page, "finance manager");
    await processDoc(page, "SHA-2512015");
    await page.goto("/inbox");
    await page.getByRole("row").filter({ hasText: "SHATINPCB" }).getByRole("button", { name: "Reconcile" }).click();
    await expect(page.getByText(/did not match our records/)).toBeVisible({ timeout: 20_000 });
    await page.goto("/disputes");
    await page.getByRole("button", { name: /Missed credit/ }).first().click();
    await page.getByRole("button", { name: "Confirm and sign" }).click();
    await expect(page.getByText(/Filed: the bank may dispute it/)).toBeVisible({ timeout: 30_000 });

    await signIn(page, "bank");
    await page.goto("/bank");
    await page.getByRole("row").filter({ hasText: "Shatin" }).getByRole("button", { name: "Dispute" }).click();
    await expect(page.getByText(/Disputed claims/)).toBeVisible({ timeout: 30_000 });

    await signIn(page, "arbiter");
    await page.goto("/bank");
    await page.getByPlaceholder("Amount to pay").fill("500");
    await page.getByRole("button", { name: "Decide" }).click();
    await expect(page.getByText(/Decided/).first()).toBeVisible({ timeout: 30_000 });

    await signIn(page, "finance manager");
    await page.goto("/disputes");
    await page.getByRole("button", { name: "All", exact: true }).click();
    await page.getByRole("button", { name: /Missed credit/ }).first().click();
    await page.getByRole("button", { name: "Pay out the claim" }).click();
    await expect(page.getByText("Paid to the company")).toBeVisible({ timeout: 30_000 });
    await page.screenshot({ path: `${SHOTS}/06-dispute.png`, fullPage: true });
  });

  test("risk setting: owner proposes, bank approves", async ({ page }) => {
    await signIn(page, "owner");
    await page.goto("/risk");
    await page.getByRole("row").filter({ hasText: "Careful" }).click();
    await page.getByRole("button", { name: "Switch on-chain" }).click();
    await expect(page.getByText(/when the bank approves it/)).toBeVisible({ timeout: 30_000 });

    await signIn(page, "bank");
    await page.goto("/bank");
    await page.getByRole("button", { name: "Approve from my wallet" }).click();
    await expect(page.getByText("Settings waiting for the bank")).toBeHidden({ timeout: 30_000 });
    await page.goto("/risk");
    await expect(page.getByRole("row").filter({ hasText: "Careful" }).getByText("Active")).toBeVisible({ timeout: 30_000 });
  });

  test("bank-detail change by email: frozen, warning sent, owner calls back and restores", async ({ page }) => {
    await signIn(page, "finance manager");
    await page.goto("/inbox");
    await page.getByRole("row").filter({ hasText: "lionrock_bank_change.eml" }).getByRole("button", { name: "Process" }).click();
    await expect(page.getByText(/Payments to this supplier are frozen/)).toBeVisible({ timeout: 20_000 });
    await page.getByRole("tab", { name: /Outbox/ }).click();
    await expect(page.getByRole("row").filter({ hasText: "Bank-change warning" }).filter({ hasText: "Lion Rock" })).toBeVisible();

    await signIn(page, "owner");
    await page.goto("/suppliers");
    await page.getByRole("row").filter({ hasText: "Lion Rock" }).click();
    await page.getByRole("button", { name: "Change payment details" }).click();
    await page.getByLabel("Number you called (from our records)").fill("+852 2555 0101");
    await page.getByLabel("Who confirmed the change").fill("Accounts manager");
    await page.getByLabel(/The supplier confirmed/).check();
    await page.getByLabel("New wallet address").fill("0x2222222222222222222222222222222222222222");
    await page.getByRole("button", { name: "Sign the change" }).click();
    await page.getByRole("button", { name: "Unfreeze" }).click();
    await expect(page.getByRole("row").filter({ hasText: "Lion Rock" }).getByText("Cool-down")).toBeVisible({ timeout: 30_000 });
  });

  test("market prices: compare buying ahead and draft a purchase order", async ({ page }) => {
    await signIn(page, "owner");
    await page.goto("/market");
    await page.getByRole("button", { name: "Compare buying the next 2 months now" }).click();
    await expect(page.getByText("Suggested")).toBeVisible({ timeout: 20_000 });
    await page.screenshot({ path: `${SHOTS}/07-market.png`, fullPage: true });
  });

  test("bank transfers: payment file, bank statement, and a debit nobody approved", async ({ page }) => {
    await signIn(page, "finance manager");
    await processDoc(page, "GAN-2512023");
    const d = page.locator(".detail");
    const approve = d.getByRole("button", { name: "Approve and sign" });
    const paid = d.getByText("Paid", { exact: true }).first();
    await expect(approve.or(paid).first()).toBeVisible({ timeout: 30_000 });
    if (await approve.isVisible()) await approve.click();  // routine bills are paid by the agent alone
    await expect(d.getByText("Paid", { exact: true }).first()).toBeVisible({ timeout: 30_000 });
    await signIn(page, "owner");
    await page.goto("/payments");
    await page.getByRole("tab", { name: "Bank transfers" }).click();
    const download = page.waitForEvent("download");
    await page.getByRole("button", { name: "Make payment file" }).click();
    expect((await download).suggestedFilename()).toMatch(/^pain001-.*\.xml$/);
    await expect(page.getByText(/Payment file .*: 1 transfer/)).toBeVisible();
    await page.getByRole("button", { name: "…with an unapproved debit" }).click();
    await expect(page.getByText(/1 payment\(s\) confirmed, 1 debit\(s\) outside the desk/)).toBeVisible();
    await expect(page.getByText(/left the bank account without an approval/)).toBeVisible();
    await expect(page.getByText("All booked")).toBeVisible();
    await page.screenshot({ path: `${SHOTS}/10-bank.png`, fullPage: true });
  });

  test("landing page: the story, then into the desk", async ({ page }) => {
    await page.context().clearCookies();
    await page.goto("/");
    await expect(page.getByRole("heading", { level: 1 })).toContainText("can't be conned");
    await expect(page.getByText("We hired an AI clerk.")).toBeVisible();
    await page.getByRole("link", { name: "Open the desk" }).first().click();
    await page.waitForURL("**/login**");
  });

  test("upload: the live reader shows each stage, every field read, then the decision", async ({ page }) => {
    await signIn(page, "finance manager");
    await page.goto("/inbox");
    // A JSON e-invoice runs the same live panel without spending vision-model quota.
    await page.locator("input[type=file]").first().setInputFiles("../data/demo/documents/t13_net30.json");
    const panel = page.getByRole("dialog", { name: "What the reader sees" });
    await expect(panel).toBeVisible();
    await expect(panel.getByText("HAR-2512011").first()).toBeVisible({ timeout: 30_000 });
    await expect(panel.getByText("✓ Decision")).toBeVisible({ timeout: 30_000 });
    await page.screenshot({ path: `${SHOTS}/11-reader.png`, fullPage: true });
    await panel.getByRole("button", { name: "Open the bill" }).click();
    await page.waitForURL("**/bills?bill=*");
    await page.getByText("What the reader saw").click();
    await expect(page.getByText("supplier says").first()).toBeVisible();
  });

  test("phone width", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await signIn(page, "finance manager");
    await page.goto("/approvals");
    await page.screenshot({ path: `${SHOTS}/08-phone.png`, fullPage: true });
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1);
    expect(overflow).toBe(false);
  });
});
