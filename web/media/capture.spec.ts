import { expect, test, type Page } from "@playwright/test";

const OUT = "../docs/readme";

async function signIn(page: Page, who: "owner" | "finance manager") {
  await page.goto("/login");
  await page.getByRole("button", { name: `Local test account: ${who}` }).click();
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await page.waitForURL("**/bills");
}

test.describe.serial("readme media", () => {
  test("landing", async ({ page }) => {
    await page.goto("/");
    await page.waitForTimeout(3000);
    await page.screenshot({ path: `${OUT}/shot-landing.png` });
  });

  test("live reader (frames for the GIF)", async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 820 });
    await signIn(page, "finance manager");
    await page.goto("/inbox");
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
    for (let i = 0; i < 8; i++) {
      await frame();
      await page.waitForTimeout(300);
    }
    await page.screenshot({ path: `${OUT}/shot-reader.png` });
  });

  test("held bill with the agent's proposal", async ({ page }) => {
    await signIn(page, "finance manager");
    await page.request.post("/api/inbox/documents/t16_fair_price");
    await page.goto("/bills");
    await page.getByText("Acme Metals").first().click();
    await expect(page.getByText(/Agent.s proposal/i)).toBeVisible();
    await page.waitForTimeout(1000);
    await page.screenshot({ path: `${OUT}/shot-bill.png` });
  });

  test("risk and controls", async ({ page }) => {
    await signIn(page, "owner");
    await page.goto("/risk");
    await page.waitForTimeout(2000);
    await page.screenshot({ path: `${OUT}/shot-risk.png` });
    await page.goto("/controls");
    await page.waitForTimeout(2000);
    await page.screenshot({ path: `${OUT}/shot-controls.png` });
  });
});
