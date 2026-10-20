import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent, type ReactNode } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import { auth, MEMBER_ROLE, type MemberRole } from "../lib/auth";
import { useMe } from "../lib/hooks";
import { ErrorLine } from "../components/ui";

function Card({ title, sub, children }: { title: string; sub?: string; children: ReactNode }) {
  return (
    <div className="center">
      <div className="login card pad">
        <div>
          <h1>{title}</h1>
          {sub && <p className="sub">{sub}</p>}
        </div>
        {children}
      </div>
    </div>
  );
}

/** Signed in but no company open: accept a waiting invitation, open a company you belong to, or create one. */
export default function Welcome() {
  const { data: me } = useMe();
  const qc = useQueryClient();
  const nav = useNavigate();
  const { data: invites } = useQuery({ queryKey: ["my-invitations"], queryFn: auth.myInvitations });
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  const pending = (invites ?? []).filter((i) => i.status === "pending");

  const go = async (fn: () => Promise<unknown>) => {
    setErr(null);
    setBusy(true);
    try {
      await fn();
      await qc.invalidateQueries();
      nav("/desk", { replace: true });
    } catch (e) {
      setErr(e);
    } finally {
      setBusy(false);
    }
  };
  const create = (e: FormEvent) => {
    e.preventDefault();
    go(async () => {
      const org = await auth.createCompany(name.trim());
      await auth.setActive(org.id);
    });
  };

  return (
    <Card title={`Welcome${me?.name ? `, ${me.name.split(" ")[0]}` : ""}`} sub="Open a company to start.">
      {pending.length > 0 && (
        <div className="stack">
          <h3>Invitations</h3>
          {pending.map((i) => (
            <div key={i.id} className="between">
              <span>
                <b>{i.organizationName ?? "A company"}</b> <span className="muted small">as {MEMBER_ROLE[i.role as MemberRole] ?? i.role}</span>
              </span>
              <button className="btn primary small" disabled={busy}
                onClick={() => go(async () => { await auth.acceptInvitation(i.id); await auth.setActive(i.organizationId); })}>
                Join
              </button>
            </div>
          ))}
        </div>
      )}
      {(me?.companies.length ?? 0) > 0 && (
        <div className="stack">
          <h3>Your companies</h3>
          {me!.companies.map((c) => (
            <div key={c.id} className="between">
              <span><b>{c.name}</b> <span className="muted small">{MEMBER_ROLE[c.role as MemberRole] ?? c.role}</span></span>
              <button className="btn small" disabled={busy} onClick={() => go(() => auth.setActive(c.id))}>Open</button>
            </div>
          ))}
        </div>
      )}
      <form className="stack" onSubmit={create}>
        <h3>Create a company</h3>
        <label className="lbl">
          Company name
          <input className="field" value={name} onChange={(e) => setName(e.target.value)} placeholder="Harbour Precision Components Ltd" required />
        </label>
        <p className="note">
          You become its owner. It starts with the sample records (suppliers, orders, receipts and the inbox) so you can try every step; connect
          your own ERP and mailbox in Settings.
        </p>
        <button className="btn primary" disabled={busy}>Create company</button>
      </form>
      <ErrorLine error={err} />
      <button className="link small" style={{ justifySelf: "start" }}
        onClick={async () => { await auth.signOut().catch(() => undefined); await qc.invalidateQueries(); nav("/login"); }}>
        Sign out
      </button>
    </Card>
  );
}

/** The link in an invitation email. Sign in (or create an account) with the invited address, then join. */
export function AcceptInvitation() {
  const { id = "" } = useParams();
  const { data: me, isLoading } = useMe();
  const qc = useQueryClient();
  const nav = useNavigate();
  const inv = useQuery({ queryKey: ["invitation", id], queryFn: () => auth.getInvitation(id), enabled: !!me, retry: false });
  const [err, setErr] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const next = `/accept-invitation/${id}`;

  if (isLoading) return <Card title="Invitation"><span className="spin" /></Card>;
  if (!me)
    return (
      <Card title="You are invited" sub="Sign in, or create an account with the email address the invitation was sent to.">
        <div className="row">
          <button className="btn primary" onClick={() => nav(`/login?next=${encodeURIComponent(next)}`)}>Sign in</button>
          <button className="btn" onClick={() => nav(`/login?mode=signup&next=${encodeURIComponent(next)}`)}>Create an account</button>
        </div>
      </Card>
    );
  if (inv.error)
    return (
      <Card title="This invitation cannot be used" sub={`It may have expired, been cancelled, or been sent to another address than ${me.email}.`}>
        <button className="btn" onClick={() => nav("/")}>Continue</button>
      </Card>
    );
  if (!inv.data) return <Card title="Invitation"><span className="spin" /></Card>;
  const i = inv.data;
  const act = async (accept: boolean) => {
    setErr(null);
    setBusy(true);
    try {
      if (accept) {
        await auth.acceptInvitation(i.id);
        await auth.setActive(i.organizationId);
      } else await auth.rejectInvitation(i.id);
      await qc.invalidateQueries();
      nav("/", { replace: true });
    } catch (e) {
      setErr(e);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Card title={`Join ${i.organizationName}`} sub={`${i.inviterEmail} invited ${i.email} as ${MEMBER_ROLE[i.role] ?? i.role}.`}>
      <div className="row">
        <button className="btn primary" disabled={busy} onClick={() => act(true)}>Join</button>
        <button className="btn" disabled={busy} onClick={() => act(false)}>Decline</button>
      </div>
      <ErrorLine error={err} />
    </Card>
  );
}

/** The link in a password-reset email. */
export function ResetPassword() {
  const [params] = useSearchParams();
  const token = params.get("token") ?? "";
  const nav = useNavigate();
  const [pw, setPw] = useState("");
  const [done, setDone] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setErr(null);
    try {
      await auth.resetPassword(token, pw);
      setDone(true);
    } catch (x) {
      setErr(x);
    }
  };
  if (!token || params.get("error"))
    return (
      <Card title="This reset link cannot be used" sub="It may have expired. Ask for a new one from the sign-in page.">
        <button className="btn" onClick={() => nav("/login")}>Back to sign in</button>
      </Card>
    );
  if (done)
    return (
      <Card title="Password changed" sub="Other sessions were signed out.">
        <button className="btn primary" onClick={() => nav("/login")}>Sign in</button>
      </Card>
    );
  return (
    <Card title="Choose a new password">
      <form className="stack" onSubmit={submit}>
        <label className="lbl">
          New password
          <input className="field" type="password" autoComplete="new-password" minLength={10} value={pw} onChange={(e) => setPw(e.target.value)} required />
        </label>
        <button className="btn primary">Save password</button>
        <ErrorLine error={err} />
      </form>
    </Card>
  );
}
