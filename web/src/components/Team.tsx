import { useQuery } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { api } from "../lib/api";
import { auth, MEMBER_ROLE, type MemberRole } from "../lib/auth";
import { ROLE, date, shortAddr } from "../lib/format";
import { useAction, useCan, useMe } from "../lib/hooks";
import { ErrorLine, Tag } from "./ui";

interface TeamRow {
  user_id: string;
  name: string;
  email: string;
  role: MemberRole;
  two_factor: boolean;
  wallet: string | null;
  signs_as: string | null;
  joined: string;
}

const ROLES: MemberRole[] = ["owner", "finance_manager", "clerk", "viewer"];
const WHAT: Record<MemberRole, string> = {
  owner: "Everything, including settings, payees, the team and the reserve",
  finance_manager: "Approves and pays bills, answers suppliers, settles disputes",
  clerk: "Brings in invoices, emails, statements and ERP data; drafts supplier queries",
  viewer: "Reads everything, changes nothing",
};

/** Settings → Team: the company's people, their roles, invitations, and which on-chain signer each one holds. */
export default function Team() {
  const { data: me } = useMe();
  const can = useCan();
  const team = useQuery({ queryKey: ["team"], queryFn: () => api.get<{ members: TeamRow[]; signers: Record<string, string> }>("/team") });
  const org = useQuery({ queryKey: ["organization"], queryFn: auth.fullOrganization });
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<MemberRole>("clerk");
  const [inviting, setInviting] = useState(false);
  const [sent, setSent] = useState("");

  const invite = useAction(async () => {
    await auth.invite(email.trim(), role);
    setSent(`Invitation sent to ${email.trim()}.`);
    setEmail("");
    setInviting(false);
  });
  const cancel = useAction((id: string) => auth.cancelInvitation(id));
  const resend = useAction(async (i: { email: string; role: MemberRole }) => {
    await auth.invite(i.email, i.role);
    setSent(`Invitation sent again to ${i.email}.`);
  });
  const setMemberRole = useAction(({ id, role }: { id: string; role: MemberRole }) => auth.setRole(id, role));
  const remove = useAction((id: string) => auth.removeMember(id));
  const [confirmRemove, setConfirmRemove] = useState<string | null>(null);

  const memberId = (userId: string) => org.data?.members.find((m) => m.userId === userId)?.id;
  const pending = (org.data?.invitations ?? []).filter((i) => i.status === "pending");
  const owners = (team.data?.members ?? []).filter((m) => m.role === "owner").length;
  const submit = (e: FormEvent) => {
    e.preventDefault();
    invite.mutate(undefined);
  };

  return (
    <div className="stack">
      <div className="card pad stack">
        <div className="between">
          <h2>Team</h2>
          {can.owner && !inviting && <button className="btn primary" onClick={() => { setSent(""); setInviting(true); }}>Invite</button>}
        </div>
        {sent && <p className="ok small">{sent}</p>}
        {inviting && (
          <form className="row" style={{ flexWrap: "wrap", alignItems: "end" }} onSubmit={submit}>
            <label className="lbl" style={{ flex: "1 1 220px" }}>
              Email
              <input className="field" type="email" autoFocus value={email} onChange={(e) => setEmail(e.target.value)} required />
            </label>
            <label className="lbl">
              Role
              <select className="field" value={role} onChange={(e) => setRole(e.target.value as MemberRole)}>
                {ROLES.map((r) => <option key={r} value={r}>{MEMBER_ROLE[r]}</option>)}
              </select>
            </label>
            <button className="btn primary" disabled={invite.isPending}>Send invitation</button>
            <button type="button" className="btn" onClick={() => setInviting(false)}>Cancel</button>
            <p className="note" style={{ flexBasis: "100%" }}>{MEMBER_ROLE[role]}: {WHAT[role]}.</p>
          </form>
        )}
        <ErrorLine error={team.error || invite.error || cancel.error || resend.error || setMemberRole.error || remove.error} />
        <div className="tablebox">
          <table>
            <thead>
              <tr><th>Name</th><th>Role</th><th>Two-step sign-in</th><th>Signing wallet</th><th>Joined</th>{can.owner && <th />}</tr>
            </thead>
            <tbody>
              {team.data?.members.map((m) => {
                const id = memberId(m.user_id);
                const self = m.email === me?.email;
                const lastOwner = m.role === "owner" && owners <= 1;
                return (
                  <tr key={m.user_id}>
                    <td>
                      <b>{m.name}</b>{self && <span className="muted small"> (you)</span>}
                      <div className="muted small">{m.email}</div>
                    </td>
                    <td>
                      {can.owner && id && !lastOwner ? (
                        <select className="field" aria-label={`Role of ${m.name}`} value={m.role} disabled={setMemberRole.isPending}
                          onChange={(e) => setMemberRole.mutate({ id, role: e.target.value as MemberRole })}>
                          {ROLES.map((r) => <option key={r} value={r}>{MEMBER_ROLE[r]}</option>)}
                        </select>
                      ) : (
                        MEMBER_ROLE[m.role] ?? m.role
                      )}
                    </td>
                    <td>{m.two_factor ? <Tag tone="ok">On</Tag> : <Tag tone={m.role === "viewer" || m.role === "clerk" ? "idle" : "review"}>Off</Tag>}</td>
                    <td>
                      {m.wallet ? (
                        <span className="mono" title={m.wallet}>
                          {shortAddr(m.wallet)} {m.signs_as && m.signs_as !== "viewer" && <span className="ok">· {ROLE[m.signs_as] ?? m.signs_as}</span>}
                        </span>
                      ) : (
                        <span className="muted">–</span>
                      )}
                    </td>
                    <td>{date(m.joined)}</td>
                    {can.owner && (
                      <td>
                        {!self && id && !lastOwner && (confirmRemove === id ? (
                          <span className="row">
                            <button className="btn small danger" onClick={() => { remove.mutate(id); setConfirmRemove(null); }}>Remove</button>
                            <button className="btn small" onClick={() => setConfirmRemove(null)}>Keep</button>
                          </span>
                        ) : (
                          <button className="btn small" onClick={() => setConfirmRemove(id)}>Remove</button>
                        ))}
                      </td>
                    )}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        {pending.length > 0 && (
          <>
            <h3>Waiting invitations</h3>
            <table>
              <tbody>
                {pending.map((i) => (
                  <tr key={i.id}>
                    <td>{i.email}</td>
                    <td>{MEMBER_ROLE[i.role] ?? i.role}</td>
                    <td className="muted small">expires {date(i.expiresAt)}</td>
                    {can.owner && (
                      <td className="row" style={{ justifyContent: "flex-end" }}>
                        <button className="btn small" disabled={resend.isPending} onClick={() => resend.mutate(i)}>Resend</button>
                        <button className="btn small" disabled={cancel.isPending} onClick={() => cancel.mutate(i.id)}>Cancel</button>
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        )}
      </div>

      <div className="card pad stack">
        <h2>On-chain signers</h2>
        <p className="note">
          Approvals and setting changes are signed on chain by these addresses, whatever the role in the desk says. A person links the wallet
          they hold in My account; a tick shows the signer is linked to someone here.
        </p>
        <table>
          <tbody>
            {Object.entries(team.data?.signers ?? {}).map(([r, a]) => {
              const holder = team.data?.members.find((m) => m.wallet?.toLowerCase() === a.toLowerCase());
              return (
                <tr key={r}>
                  <td>{ROLE[r] ?? r}</td>
                  <td className="mono">{shortAddr(a)}</td>
                  <td>{holder ? <span className="ok">✓ {holder.name}</span> : r === "underwriter" || r === "arbiter" ? <span className="muted">Outside the company</span> : <span className="muted">Not linked</span>}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
