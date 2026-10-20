import { expect, test, type Page } from "@playwright/test";

const SHOTS = process.env.SHOTS ?? "/tmp/shots";

const NAV: Record<string, string> = { "/desk": "Desk", "/risk": "Risk", "/security": "Security", "/activity": "Activity", "/settings": "Settings" };

/** Log in through the wallet login page with a local dev account, then go to a page with the header nav. */
async function connect(page: Page, who: "owner" | "finance manager", to = "/desk") {
  await page.goto("/login");
  await page.getByRole("radio", { name: who === "owner" ? /^Owner/ : /^Finance manager/ }).click();
  await page.getByRole("button", { name: "Local test key" }).click();
  await page.waitForURL("**/desk");
  await expect(page.locator(".rolechip")).toContainText(who === "owner" ? "Owner" : "Finance manager");
  if (to !== "/desk") await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: NAV[to] }).click();
}

/** Open a document from the inbox by its key, through the UI. */
async function openDoc(page: Page, key: string) {
  const inbox = await (await page.request.get("/api/inbox")).json();
  const d = inbox.documents.find((x: any) => x.key === key);
  const total = `$${d.total.toLocaleString("en-US", { minimumFractionDigits: 2 })}`;
  await page.getByRole("button", { name: new RegExp(`${d.supplier.replace(/[()]/g, ".")}.*${total.replace(/[$.]/g, "\\$&")}`) }).click();
}

test.describe.serial("payables desk", () => {
  test("routine bill paid alone", async ({ page }) => {
    await connect(page, "finance manager");
    await expect(page.getByText("Pick something from the list")).toBeVisible();
    await page.screenshot({ path: `${SHOTS}/01-desk-empty.png` });
    await openDoc(page, "t01_routine");
    await expect(page.getByText("Paid by the agent on its own.")).toBeVisible();
    await page.screenshot({ path: `${SHOTS}/02-bill-paid-alone.png` });
  });

  test("inbox: look-alike email, bank-change email, statement opens a case", async ({ page }) => {
    await connect(page, "finance manager");
    await page.request.post("/api/inbox/documents/t04_missed_credit");
    await page.getByRole("button", { name: /lionrock bank change/i }).click();
    await expect(page.getByText("Asked to change bank details").first()).toBeVisible({ timeout: 20_000 });
    await page.getByRole("button", { name: /SHATINPCB-2025-12/ }).click();
    await expect(page.getByText(/Overpaid/).first()).toBeVisible({ timeout: 20_000 });
    await page.screenshot({ path: `${SHOTS}/13-case.png` });
    await page.getByRole("button", { name: "Confirm and sign" }).click();
    await expect(page.getByText("Owed back, recorded on-chain")).toBeVisible({ timeout: 30_000 });
  });

  test("upload: the reader panel shows each stage and the extracted fields", async ({ page }) => {
    await connect(page, "finance manager");
    // A JSON e-invoice runs the same live panel without spending vision-model quota.
    await page.locator('input[type=file]').setInputFiles("../data/demo/documents/t13_net30.json");
    await expect(page.getByRole("heading", { name: "What the reader sees" })).toBeVisible();
    await expect(page.getByText("HAR-2512011").first()).toBeVisible({ timeout: 30_000 });
    await expect(page.getByRole("button", { name: "Open the bill" })).toBeVisible({ timeout: 30_000 });
    await page.screenshot({ path: `${SHOTS}/16-reader.png`, fullPage: true });
    await page.getByRole("button", { name: "Open the bill" }).click();
    await page.getByText("What the reader saw").click();
    await expect(page.getByText("supplier says").first()).toBeVisible();
  });

  test("fair price: query, reply, signed approval", async ({ page }) => {
    await connect(page, "finance manager");
    await openDoc(page, "t16_fair_price");
    await expect(page.getByText(/Needs your signature. The price is up/)).toBeVisible();
    await page.screenshot({ path: `${SHOTS}/03-fair-price.png` });
    await page.getByRole("button", { name: "Ask the supplier about the price" }).click();
    await page.getByRole("button", { name: /^Send to/ }).click();
    await expect(page.getByText(/Query sent/)).toBeVisible();
    const qid = (await page.getByText(/Query sent/).textContent())!.match(/Q-\d{3}/)![0];
    const over = (await page.getByText("Over the fair price", { exact: true }).first().locator("..").textContent())!.match(/\$([\d,]+\.\d{2})/)![1];
    await page.getByLabel(/Paste their email/).fill(`From: Acme Accounts <accounts@acme-hk.com>\nSubject: Re: ${qid}\n\nCredit note CN-7781 for USD ${over} is attached.`);
    await page.getByRole("button", { name: "Record reply" }).click();
    await expect(page.getByText("The supplier sent a credit note")).toBeVisible();
    await page.getByRole("button", { name: /Sign and pay/ }).click();
    await expect(page.getByText("Paid after the finance manager signed.")).toBeVisible({ timeout: 30_000 });
    await page.screenshot({ path: `${SHOTS}/04-fair-price-paid.png` });
  });

  test("request: one question, then a plan that runs", async ({ page }) => {
    await connect(page, "owner");
    for (const k of ["t19_acme_0", "t19_acme_1"]) await page.request.post(`/api/inbox/documents/${k}?process=false`);
    await page.getByLabel("Tell the agent what to do").fill("Pay the copper supplier");
    await page.getByRole("button", { name: "Plan", exact: true }).click();
    await expect(page.getByText("Which supplier?")).toBeVisible();
    await page.screenshot({ path: `${SHOTS}/05-question.png` });
    await page.getByRole("button", { name: "Acme Metals (HK) Ltd", exact: true }).click();
    await expect(page.getByRole("button", { name: "Run" })).toBeVisible();
    await page.screenshot({ path: `${SHOTS}/06-plan.png` });
    await page.getByRole("button", { name: "Run" }).click();
    await expect(page.getByText("Done.")).toBeVisible({ timeout: 30_000 });
    await page.screenshot({ path: `${SHOTS}/07-plan-done.png` });
  });

  test("risk: owner switches on-chain", async ({ page }) => {
    await connect(page, "owner", "/risk");
    await page.getByRole("radio", { name: /Careful/ }).click();
    await page.screenshot({ path: `${SHOTS}/08-risk.png`, fullPage: true });
    await page.getByRole("button", { name: "Switch to careful" }).click();
    await expect(page.getByText("This setting is active on-chain.")).toBeVisible({ timeout: 30_000 });
  });

  test("security: poisoned invoice to both agents", async ({ page }) => {
    await page.goto("/security");
    await page.getByRole("button", { name: "Send the invoice to both" }).click();
    await expect(page.getByText(/It followed the text and sent/)).toBeVisible({ timeout: 30_000 });
    await expect(page.getByText(/nothing moved/i)).toBeVisible();
    await page.screenshot({ path: `${SHOTS}/09-security.png`, fullPage: true });
  });

  test("activity", async ({ page }) => {
    await page.goto("/activity");
    await expect(page.getByText(/So far the agent has/)).toBeVisible();
    await page.screenshot({ path: `${SHOTS}/10-activity.png` });
    await page.getByRole("tab", { name: "Tasks and contracts" }).click();
    await expect(page.getByText("Our records and the chain agree")).toBeVisible();
  });

  test("refusals: payee change and owner-only request", async ({ page }) => {
    await connect(page, "finance manager");
    await page.getByRole("button", { name: "Add a new bank account for Acme" }).click();
    await page.getByRole("button", { name: "Plan", exact: true }).click();
    await expect(page.getByText(/can't|cannot|not something/i).first()).toBeVisible();
    await page.screenshot({ path: `${SHOTS}/12-refusal.png` });
  });

  test("security: pause, banner, owner resumes", async ({ page }) => {
    await connect(page, "owner", "/security");
    await page.getByRole("button", { name: "Pause the agent" }).click();
    await expect(page.getByText("The agent is paused.").first()).toBeVisible({ timeout: 15_000 });
    await page.screenshot({ path: `${SHOTS}/14-paused.png` });
    await page.getByRole("button", { name: "Resume" }).click();
    await expect(page.getByText("The agent is running.")).toBeVisible({ timeout: 30_000 });
  });

  test("settings: payees, unfreeze, demo controls", async ({ page }) => {
    await connect(page, "owner", "/settings");
    await expect(page.getByRole("heading", { name: "Payees" })).toBeVisible();
    await page.screenshot({ path: `${SHOTS}/15-settings.png`, fullPage: true });
    await page.getByRole("button", { name: /^Unfreeze Lion Rock/ }).click();
    await expect(page.getByRole("button", { name: /^Unfreeze Lion Rock/ })).toHaveCount(0, { timeout: 30_000 });
    await page.getByRole("button", { name: "Move to the next day" }).click();
    await expect(page.getByText(/anchored on-chain/)).toBeVisible({ timeout: 30_000 });
  });

  test("landing, viewer, not found", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByRole("heading", { level: 1 })).toContainText("can't be conned");
    await page.screenshot({ path: `${SHOTS}/00-landing.png` });
    await page.getByRole("link", { name: "Open the desk" }).first().click();
    await page.getByRole("radio", { name: /^Look around/ }).click();
    await page.getByRole("button", { name: "Look around without a wallet" }).click();
    await expect(page.locator(".rolechip")).toContainText("Viewer");
    await page.goto("/nowhere");
    await expect(page.getByText("Page not found")).toBeVisible();
  });

  test("phone width", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/desk");
    await expect(page.getByText("Needs you")).toBeVisible();
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    expect(overflow).toBeLessThanOrEqual(0);
    await page.screenshot({ path: `${SHOTS}/11-phone.png` });
  });
});
