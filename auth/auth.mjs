// Better Auth for the payables desk: email and password with two-factor, companies (organisations) with roles,
// invitations. Shares the Postgres database with the API (DATABASE_URL); the API reads the session and the
// member's role from the same tables (apagent/identity.py).
import { betterAuth } from "better-auth";
import { haveIBeenPwned, organization, twoFactor } from "better-auth/plugins";
import { createAccessControl } from "better-auth/plugins/access";
import { defaultStatements, memberAc, ownerAc } from "better-auth/plugins/organization/access";
import pg from "pg";

// Company roles. Only the owner manages members and invitations; what each role may do in the desk itself is
// decided by the API from the role name (owner, finance_manager, clerk, viewer).
const ac = createAccessControl(defaultStatements);
const roles = {
  owner: ac.newRole(ownerAc.statements),
  finance_manager: ac.newRole(memberAc.statements),
  clerk: ac.newRole(memberAc.statements),
  viewer: ac.newRole(memberAc.statements),
};

const ROLE_LABEL = { owner: "owner", finance_manager: "finance manager", clerk: "accounts clerk", viewer: "viewer" };
const base = process.env.PUBLIC_URL || "http://127.0.0.1:8000";
const pool = new pg.Pool({ connectionString: process.env.DATABASE_URL, max: 5 });

const api = process.env.API_INTERNAL_URL || "http://127.0.0.1:8000";

/** Invitation, verification and password-reset mail is sent by the API through the company mailbox (apagent/mail.py),
 * so there is one mail setup. If the API cannot be reached the message is logged instead. */
async function sendMail(to, subject, text) {
  try {
    const r = await fetch(`${api}/api/internal/mail`, {
      method: "POST",
      headers: { "content-type": "application/json", "x-internal-token": process.env.BETTER_AUTH_SECRET },
      body: JSON.stringify({ to, subject, text }),
    });
    if (r.ok) return;
    console.error(`mail to ${to} refused by the API: ${r.status}`);
  } catch (e) {
    console.error(`mail to ${to} not sent: ${e.message}`);
  }
  console.log(`[mail to ${to}] ${subject}\n${text}`);
}

export const auth = betterAuth({
  appName: "Payables Desk",
  baseURL: base,
  basePath: "/api/auth",
  secret: process.env.BETTER_AUTH_SECRET,
  trustedOrigins: [base, "http://127.0.0.1:5173", "http://localhost:5173"],
  database: pool,
  databaseHooks: {
    session: {
      create: {
        // A new sign-in opens the company the person last opened (or joined first), so they land on the desk.
        async before(session) {
          const r = await pool.query(
            `select m."organizationId" from member m left join session s on s."userId" = m."userId" and s."activeOrganizationId" = m."organizationId"
             where m."userId" = $1 group by m."organizationId", m."createdAt" order by max(s."updatedAt") desc nulls last, m."createdAt" limit 1`,
            [session.userId],
          );
          return { data: { ...session, activeOrganizationId: r.rows[0]?.organizationId ?? null } };
        },
      },
    },
  },
  emailAndPassword: {
    enabled: true,
    minPasswordLength: 10,
    autoSignIn: true,
    requireEmailVerification: process.env.REQUIRE_EMAIL_VERIFICATION === "on",
    revokeSessionsOnPasswordReset: true,
    async sendResetPassword({ user, url }) {
      await sendMail(user.email, "Reset your Payables Desk password", `Reset your password: ${url}\n\nIf you did not ask for this, ignore this message.\n`);
    },
  },
  emailVerification: {
    sendOnSignUp: process.env.REQUIRE_EMAIL_VERIFICATION === "on",
    autoSignInAfterVerification: true,
    async sendVerificationEmail({ user, url }) {
      await sendMail(user.email, "Confirm your email for the Payables Desk", `Confirm your email: ${url}\n`);
    },
  },
  session: { expiresIn: 60 * 60 * 12, updateAge: 60 * 60 },
  // Sign-in and sign-up have tighter built-in limits; the API passes the caller's address in x-forwarded-for.
  rateLimit: { enabled: process.env.AUTH_RATE_LIMIT !== "off", window: 60, max: 30 },
  advanced: { cookiePrefix: "desk" },
  plugins: [
    organization({
      ac,
      roles,
      creatorRole: "owner",
      allowUserToCreateOrganization: true,
      async sendInvitationEmail(data) {
        const link = `${base}/accept-invitation/${data.id}`;
        await sendMail(
          data.email,
          `You are invited to ${data.organization.name} on the Payables Desk`,
          `${data.inviter.user.name} invited you to join ${data.organization.name} as ${ROLE_LABEL[data.role] ?? data.role}.\n\nAccept: ${link}\n`,
        );
      },
    }),
    twoFactor({ issuer: "Payables Desk" }),
    haveIBeenPwned(),
  ],
});
