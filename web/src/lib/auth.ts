// The login service (auth/, Better Auth), reached through the API at /api/auth/*. Company staff sign in with email
// and password; companies, roles and invitations are Better Auth organisations, members and invitations.
import { api } from "./api";

export type MemberRole = "owner" | "finance_manager" | "clerk" | "viewer";

export const MEMBER_ROLE: Record<MemberRole, string> = {
  owner: "Owner",
  finance_manager: "Finance manager",
  clerk: "Accounts clerk",
  viewer: "Viewer",
};

export interface Invitation {
  id: string;
  email: string;
  role: MemberRole;
  status: "pending" | "accepted" | "rejected" | "canceled";
  organizationId: string;
  organizationName?: string;
  inviterId: string;
  expiresAt: string;
  createdAt?: string;
}

export interface FullOrganization {
  id: string;
  name: string;
  slug: string;
  members: { id: string; userId: string; role: MemberRole; createdAt: string; user: { id: string; name: string; email: string } }[];
  invitations: Invitation[];
}

const slugify = (name: string) =>
  name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 40) + "-" + Math.random().toString(36).slice(2, 7);

export const auth = {
  signIn: (email: string, password: string) =>
    api.post<{ twoFactorRedirect?: boolean; user?: { id: string } }>("/auth/sign-in/email", { email, password, rememberMe: true }),
  signUp: (name: string, email: string, password: string) => api.post("/auth/sign-up/email", { name, email, password }),
  signOut: () => api.post("/auth/sign-out"),
  verifyTotp: (code: string, trustDevice: boolean) => api.post("/auth/two-factor/verify-totp", { code, trustDevice }),
  verifyBackupCode: (code: string) => api.post("/auth/two-factor/verify-backup-code", { code }),
  enableTwoFactor: (password: string) => api.post<{ totpURI: string; backupCodes: string[] }>("/auth/two-factor/enable", { password }),
  disableTwoFactor: (password: string) => api.post("/auth/two-factor/disable", { password }),
  requestReset: (email: string) =>
    api.post("/auth/request-password-reset", { email, redirectTo: `${window.location.origin}/reset-password` }),
  resetPassword: (token: string, newPassword: string) => api.post("/auth/reset-password", { token, newPassword }),
  changePassword: (currentPassword: string, newPassword: string) =>
    api.post("/auth/change-password", { currentPassword, newPassword, revokeOtherSessions: true }),

  createCompany: (name: string) => api.post<{ id: string }>("/auth/organization/create", { name, slug: slugify(name) }),
  setActive: (organizationId: string) => api.post("/auth/organization/set-active", { organizationId }),
  fullOrganization: () => api.get<FullOrganization | null>("/auth/organization/get-full-organization"),
  invite: (email: string, role: MemberRole) =>
    api.post<Invitation>("/auth/organization/invite-member", { email, role, resend: true }),
  cancelInvitation: (invitationId: string) => api.post("/auth/organization/cancel-invitation", { invitationId }),
  myInvitations: () => api.get<Invitation[]>("/auth/organization/list-user-invitations"),
  getInvitation: (id: string) =>
    api.get<Invitation & { organizationName: string; inviterEmail: string }>(`/auth/organization/get-invitation?id=${encodeURIComponent(id)}`),
  acceptInvitation: (invitationId: string) =>
    api.post<{ member: { organizationId: string } }>("/auth/organization/accept-invitation", { invitationId }),
  rejectInvitation: (invitationId: string) => api.post("/auth/organization/reject-invitation", { invitationId }),
  setRole: (memberId: string, role: MemberRole) => api.post("/auth/organization/update-member-role", { memberId, role }),
  removeMember: (memberIdOrEmail: string) => api.post("/auth/organization/remove-member", { memberIdOrEmail }),
};
