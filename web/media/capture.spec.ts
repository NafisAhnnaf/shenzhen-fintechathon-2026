import { expect, test, type Page } from "@playwright/test";

// README media: real screenshots of the purple desk and the frames of the live-reader GIF. Run against the API on
// :8000 on fresh contracts (one PDF goes through the vision reader):
//   PW_CHANNEL=chrome npx playwright test -c media/media.config.ts
const OUT = "../docs/readme";

async function signIn(page: Page, who: "Owner" | "Finance manager") {
  await page.context().clearCookies();
  await page.goto("/login");
  await page.getByRole("radio", { name: new RegExp(`^${who}`) }).click();
  await page.getByRole("button", { name: "Local test key" }).click();
  await page.waitForURL("**/desk", { timeout: 20_000 });
}

test.describe.serial("readme media", () => {
  test("landing", async ({ page }) => {
    await page.goto("/");
    await page.waitForTimeout(3000);
    await page.screenshot({ path: `${OUT}/shot-landing.png` });
  });

  test("risk dial and security", async ({ page }) => {
    await signIn(page, "Owner");
    await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Risk" }).click();
    await page.waitForTimeout(1800);
    await page.screenshot({ path: `${OUT}/shot-risk.png` });
    await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Security" }).click();
    await page.getByRole("button", { name: "Send the poisoned invoice" }).click();
    await expect(page.getByText(/nothing moved/i)).toBeVisible({ timeout: 30_000 });
    await page.waitForTimeout(800);
    await page.screenshot({ path: `${OUT}/shot-controls.png` });
  });

  test("the team's payments register inside the purple shell", async ({ page }) => {
    await signIn(page, "Owner");
    await page.getByRole("button", { name: /More/ }).click();
    await page.getByRole("menuitem", { name: "Payments" }).click();
    await page.waitForTimeout(1500);
    await page.screenshot({ path: `${OUT}/shot-payments.png` });
  });

  test("live reader on the desk (frames for the GIF)", async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 820 });
    await signIn(page, "Owner");
    expect((await page.request.post("/api/admin/reset")).ok()).toBeTruthy(); // the security shot already took this bill
    await signIn(page, "Finance manager");
    await page.waitForTimeout(800);
    let n = 0;
    const frame = async () => page.screenshot({ path: `media/frames/f${String(n++).padStart(3, "0")}.png` });
    for (let i = 0; i < 3; i++) await frame();
    await page.locator("input[type=file]").first().setInputFiles("../data/demo/documents/t07_poisoned.pdf");
    const done = page.getByRole("button", { name: "Open the bill" });
    for (let i = 0; i < 160 && !(await done.isVisible()); i++) {
      await frame();
      await page.waitForTimeout(350);
    }
    for (let i = 0; i < 6; i++) {
      await frame();
      await page.waitForTimeout(300);
    }
    await page.locator("pre").first().scrollIntoViewIfNeeded();
    for (let i = 0; i < 8; i++) await frame();
    await page.screenshot({ path: `${OUT}/shot-reader.png` });
  });

  test("fair-price bill on the desk", async ({ page }) => {
    await signIn(page, "Finance manager");
    await page.request.post("/api/inbox/documents/t16_fair_price");
    await page.reload();
    await page.locator(".qcol .card").first().getByRole("button", { name: /Acme Metals/ }).click();
    await expect(page.getByText(/The price is up/)).toBeVisible();
    await page.waitForTimeout(1200);
    await page.screenshot({ path: `${OUT}/shot-bill.png` });
  });


});
