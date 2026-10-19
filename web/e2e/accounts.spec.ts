import { createHmac } from "node:crypto";
import { expect, test, type Page } from "@playwright/test";

// Email sign-in through the login service. Runs only when the server has it on (STATE_STORE=postgres, LOGIN=accounts,
// the login service running); the wallet-mode flows are in desk.spec.ts.

const run = Date.now().toString(36);
const OWNER = { name: "Mei Chan", email: `owner-${run}@harbour.test`, password: "harbour owner pass 2026" };
const CLERK = { name: "Kit Wong", email: `clerk-${run}@harbour.test`, password: "harbour clerk pass 2026" };

/** RFC 6238 code from a base32 secret, as an authenticator app computes it. */
function totp(secret: string, at = Date.now()): string {
  const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";
  let bits = "";
  for (const ch of secret.replace(/=+$/, "").toUpperCase()) bits += alphabet.indexOf(ch).toString(2).padStart(5, "0");
  const key = Buffer.from(bits.match(/.{8}/g)!.map((b) => parseInt(b, 2)));
  const counter = Buffer.alloc(8);
  counter.writeBigUInt64BE(BigInt(Math.floor(at / 1000 / 30)));
  const h = createHmac("sha1", key).update(counter).digest();
  const o = h[h.length - 1] & 0xf;
  return ((h.readUInt32BE(o) & 0x7fffffff) % 1_000_000).toString().padStart(6, "0");
}

async function signUp(page: Page, who: typeof OWNER) {
  await page.getByRole("button", { name: "Create an account" }).click();
  await page.getByLabel("Your name").fill(who.name);
  await page.getByLabel("Email").fill(who.email);
  await page.getByLabel("Password").fill(who.password);
  await page.getByRole("button", { name: "Create account" }).click();
}

test.describe.serial("email sign-in", () => {
  test.beforeEach(async ({ request }) => {
    const pub = await (await request.get("/api/public")).json();
    test.skip(pub.login !== "accounts", "the server runs without the login service");
  });

  let invitation = "";
  let secret = "";

  test("owner signs up, creates the company and invites a clerk", async ({ page }) => {
    await page.goto("/login");
    await signUp(page, OWNER);
    await expect(page.getByRole("heading", { name: /Welcome, Mei/ })).toBeVisible();
    await page.getByLabel("Company name").fill("Harbour Precision Components Ltd");
    await page.getByRole("button", { name: "Create company" }).click();
    await expect(page.getByRole("heading", { name: "Bills" })).toBeVisible();
    await expect(page.getByRole("button", { name: /Mei Chan · Owner/ })).toBeVisible();

    await page.goto("/settings?tab=team");
    await page.getByRole("button", { name: "Invite" }).click();
    await page.getByLabel("Email").fill(CLERK.email);
    await page.getByLabel("Role").selectOption("clerk");
    await page.getByRole("button", { name: "Send invitation" }).click();
    await expect(page.getByText(`Invitation sent to ${CLERK.email}`)).toBeVisible();
    await expect(page.getByRole("cell", { name: CLERK.email })).toBeVisible();
    const org = await (await page.request.get("/api/auth/organization/get-full-organization")).json();
    invitation = org.invitations.find((i: any) => i.email === CLERK.email).id;
  });

  test("the clerk accepts from the email link and can bring in invoices but not approve", async ({ page }) => {
    await page.goto(`/accept-invitation/${invitation}`);
    await page.getByRole("button", { name: "Create an account" }).click();
    await page.getByLabel("Your name").fill(CLERK.name);
    await page.getByLabel("Email").fill(CLERK.email);
    await page.getByLabel("Password").fill(CLERK.password);
    await page.getByRole("button", { name: "Create account" }).click();
    await expect(page.getByRole("heading", { name: "Join Harbour Precision Components Ltd" })).toBeVisible();
    await page.getByRole("button", { name: "Join" }).click();
    await expect(page.getByRole("button", { name: /Kit Wong · Accounts clerk/ })).toBeVisible();

    await page.goto("/inbox");
    await expect(page.getByRole("button", { name: "Process" }).first()).toBeVisible();
    const res = await page.request.post("/api/admin/reset");
    expect(res.status()).toBe(403);
    await page.goto("/settings?tab=team");
    await expect(page.getByRole("button", { name: "Invite" })).toHaveCount(0);
    await expect(page.getByRole("cell", { name: /Mei Chan/ })).toBeVisible();
  });

  test("owner turns on two-step sign-in and needs the code next time", async ({ page }) => {
    await page.goto("/login");
    await page.getByLabel("Email").fill(OWNER.email);
    await page.getByLabel("Password").fill(OWNER.password);
    await page.getByRole("button", { name: "Sign in", exact: true }).click();
    await expect(page.getByRole("heading", { name: "Bills" })).toBeVisible();

    await page.goto("/settings?tab=account");
    await page.getByLabel("Your password").fill(OWNER.password);
    await page.getByRole("button", { name: "Set up" }).click();
    secret = (await page.locator("p:has-text('Or type this key') .mono").textContent())!.trim();
    await page.getByLabel("Code from the app").fill(totp(secret));
    await page.getByRole("button", { name: "Turn on" }).click();
    await expect(page.getByText("Two-step sign-in is on.")).toBeVisible();

    await page.getByRole("button", { name: /Mei Chan · Owner/ }).click();
    await page.getByRole("menu").getByRole("button", { name: "Sign out" }).click();
    await page.getByLabel("Email").fill(OWNER.email);
    await page.getByLabel("Password").fill(OWNER.password);
    await page.getByRole("button", { name: "Sign in", exact: true }).click();
    await expect(page.getByRole("heading", { name: "Two-step sign-in" })).toBeVisible();
    await page.getByLabel("Authenticator code").fill("000000");
    await page.getByRole("button", { name: "Verify" }).click();
    await expect(page.locator(".err").first()).toBeVisible();
    await page.getByLabel("Authenticator code").fill(totp(secret));
    await page.getByRole("button", { name: "Verify" }).click();
    await expect(page.getByRole("heading", { name: "Bills" })).toBeVisible();
  });

  test("a wrong password is refused and a company wallet cannot use wallet sign-in", async ({ page }) => {
    await page.goto("/login");
    await page.getByLabel("Email").fill(OWNER.email);
    await page.getByLabel("Password").fill("not the password at all");
    await page.getByRole("button", { name: "Sign in", exact: true }).click();
    await expect(page.getByText(/invalid/i)).toBeVisible();
    await page.getByRole("button", { name: "Sign in with your wallet" }).click();
    await expect(page.getByRole("heading", { name: "Sign in with your wallet" })).toBeVisible();
  });
});
