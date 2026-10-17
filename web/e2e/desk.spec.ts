import { expect, test, type Page } from "@playwright/test";

const SHOTS = process.env.SHOTS ?? "/tmp/shots";

async function connect(page: Page, who: "owner" | "finance manager") {
  const disconnect = page.getByRole("button", { name: "Disconnect" });
  if (await disconnect.isVisible()) await disconnect.click();
  await page.getByRole("button", { name: "Connect wallet" }).click();
  await page.getByRole("button", { name: `Local dev account: ${who}` }).click();
  await expect(page.getByText(who === "owner" ? "Owner" : "Finance manager", { exact: false }).first()).toBeVisible();
}

/** Open a document from the inbox by its key, through the UI. */
async function openDoc(page: Page, key: string) {
  const inbox = await (await page.request.get("/api/inbox")).json();
  const d = inbox.documents.find((x: any) => x.key === key);
  await page.getByRole("button", { name: /^Inbox/ }).click();
  const total = `$${d.total.toLocaleString("en-US", { minimumFractionDigits: 2 })}`;
  await page.getByRole("button", { name: new RegExp(`${d.supplier.replace(/[()]/g, ".")}.*${total.replace(/[$.]/g, "\\$&")}`) }).click();
}

test.describe.serial("payables desk", () => {
  test("routine bill paid alone", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByText("Pick something from the list")).toBeVisible();
    await page.screenshot({ path: `${SHOTS}/01-desk-empty.png` });
    await connect(page, "finance manager");
    await openDoc(page, "t01_routine");
    await expect(page.getByText("Paid by the agent on its own.")).toBeVisible();
    await page.screenshot({ path: `${SHOTS}/02-bill-paid-alone.png` });
  });

  test("fair price: query, reply, signed approval", async ({ page }) => {
    await page.goto("/");
    await connect(page, "finance manager");
    await openDoc(page, "t16_fair_price");
    await expect(page.getByText(/Needs your signature. The price is up/)).toBeVisible();
    await page.screenshot({ path: `${SHOTS}/03-fair-price.png` });
    await page.getByRole("button", { name: "Ask the supplier about the price" }).click();
    await page.getByRole("button", { name: /^Send to/ }).click();
    await expect(page.getByText(/Query sent/)).toBeVisible();
    const qid = (await page.getByText(/Query sent/).textContent())!.match(/Q-\d{3}/)![0];
    const over = (await page.getByText("Over the fair price").locator("..").textContent())!.match(/\$([\d,]+\.\d{2})/)![1];
    await page.getByLabel(/Paste their email/).fill(`From: Acme Accounts <accounts@acme-hk.com>\nSubject: Re: ${qid}\n\nCredit note CN-7781 for USD ${over} is attached.`);
    await page.getByRole("button", { name: "Record reply" }).click();
    await expect(page.getByText("The supplier sent a credit note")).toBeVisible();
    await page.getByRole("button", { name: /Sign and pay/ }).click();
    await expect(page.getByText("Paid after the finance manager signed.")).toBeVisible({ timeout: 30_000 });
    await page.screenshot({ path: `${SHOTS}/04-fair-price-paid.png` });
  });

  test("request: one question, then a plan that runs", async ({ page }) => {
    await page.goto("/");
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
    await page.goto("/risk");
    await connect(page, "owner");
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

  test("phone width", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/");
    await expect(page.getByText("Needs you")).toBeVisible();
    await page.screenshot({ path: `${SHOTS}/11-phone.png` });
  });
});
