import { useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useAccount, useConnect, useDisconnect, useSignMessage } from "wagmi";
import { api, type Me } from "../lib/api";
import { auth } from "../lib/auth";
import { ROLE, shortAddr } from "../lib/format";
import { usePublic } from "../lib/hooks";
import { connectorLabel, roleOf } from "../lib/wallet";
import { ErrorLine } from "../components/ui";

type Mode = "signin" | "signup" | "code" | "forgot" | "sent" | "wallet";

/** Company staff sign in with email and password (and an authenticator code when they turned it on). The bank and
 * the arbiter, who are outside the company, sign in with their wallets. Without the login service (local runs) the
 * wallet is the only way in. */
export default function Login() {
  const { data: pub } = usePublic();
  const [params] = useSearchParams();
  const [mode, setMode] = useState<Mode>(params.get("mode") === "signup" ? "signup" : "signin");
  const want = params.get("next") ?? "";
  const next = want.startsWith("/") && !want.startsWith("//") && !want.startsWith("/\\") ? want : "/bills";
  // With email sign-in one server holds many companies, so the page names the product, not one company.
  const company = pub?.login === "wallet" ? pub.company.replace(" (fictional)", "") : "Payables Desk";

  return (
    <div className="center">
      <div className="login card pad">
        <div className="brand" style={{ padding: 0 }}>
          <div className="mark">{company[0]}</div>
          <div>
            <b>{company}</b>
            <span>Accounts payable</span>
          </div>
        </div>
        {pub?.login === "wallet" || mode === "wallet" ? (
          <WalletSignIn back={pub?.login === "accounts" ? () => setMode("signin") : undefined} next={next} />
        ) : (
          <AccountSignIn mode={mode} setMode={setMode} next={next} email={params.get("email") ?? ""} />
        )}
      </div>
    </div>
  );
}

function AccountSignIn({ mode, setMode, next, email: initialEmail }: { mode: Mode; setMode: (m: Mode) => void; next: string; email: string }) {
  const qc = useQueryClient();
  const nav = useNavigate();
  const [name, setName] = useState("");
  const [email, setEmail] = useState(initialEmail);
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [backup, setBackup] = useState(false);
  const [trust, setTrust] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<unknown>(null);

  const done = async () => {
    await qc.invalidateQueries();
    nav(next, { replace: true });
  };

  const run = (fn: () => Promise<void>) => async (e: FormEvent) => {
    e.preventDefault();
    setErr(null);
    setBusy(true);
    try {
      await fn();
    } catch (x) {
      setErr(x);
    } finally {
      setBusy(false);
    }
  };

  const signIn = run(async () => {
    const r = await auth.signIn(email.trim(), password);
    if (r?.twoFactorRedirect) {
      setPassword("");
      setMode("code");
      return;
    }
    await done();
  });
  const signUp = run(async () => {
    await auth.signUp(name.trim(), email.trim(), password);
    await done();
  });
  const verify = run(async () => {
    if (backup) await auth.verifyBackupCode(code.trim());
    else await auth.verifyTotp(code.replace(/\s/g, ""), trust);
    await done();
  });
  const forgot = run(async () => {
    await auth.requestReset(email.trim());
    setMode("sent");
  });

  if (mode === "code")
    return (
      <form className="stack" onSubmit={verify}>
        <div>
          <h1>Two-step sign-in</h1>
          <p className="sub">{backup ? "Enter one of the backup codes you saved." : "Enter the 6-digit code from your authenticator app."}</p>
        </div>
        <label className="lbl">
          {backup ? "Backup code" : "Authenticator code"}
          <input className="field" autoFocus inputMode={backup ? "text" : "numeric"} autoComplete="one-time-code" value={code}
            onChange={(e) => setCode(e.target.value)} required />
        </label>
        {!backup && (
          <label className="radio small">
            <input type="checkbox" checked={trust} onChange={(e) => setTrust(e.target.checked)} /> Trust this browser for 30 days
          </label>
        )}
        <div className="row">
          <button className="btn primary" disabled={busy}>Verify</button>
          <button type="button" className="link" onClick={() => { setBackup(!backup); setCode(""); }}>
            {backup ? "Use the authenticator app" : "Use a backup code"}
          </button>
        </div>
        <ErrorLine error={err} />
      </form>
    );

  if (mode === "forgot" || mode === "sent")
    return (
      <form className="stack" onSubmit={forgot}>
        <div>
          <h1>Reset your password</h1>
          <p className="sub">
            {mode === "sent" ? "If that email has an account, a reset link is on its way. The link works for one hour." : "We will email you a link to choose a new password."}
          </p>
        </div>
        {mode === "forgot" && (
          <>
            <label className="lbl">
              Email
              <input className="field" type="email" autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
            </label>
            <button className="btn primary" disabled={busy}>Send the link</button>
          </>
        )}
        <button type="button" className="link" onClick={() => setMode("signin")}>Back to sign in</button>
        <ErrorLine error={err} />
      </form>
    );

  const signup = mode === "signup";
  return (
    <form className="stack" onSubmit={signup ? signUp : signIn}>
      <div>
        <h1>{signup ? "Create your account" : "Sign in"}</h1>
        {signup && <p className="sub">Then create your company or accept an invitation from your owner.</p>}
      </div>
      {signup && (
        <label className="lbl">
          Your name
          <input className="field" autoComplete="name" value={name} onChange={(e) => setName(e.target.value)} required />
        </label>
      )}
      <label className="lbl">
        Email
        <input className="field" type="email" autoComplete="email" autoFocus value={email} onChange={(e) => setEmail(e.target.value)} required />
      </label>
      <label className="lbl">
        Password
        <input className="field" type="password" autoComplete={signup ? "new-password" : "current-password"} minLength={signup ? 10 : undefined}
          value={password} onChange={(e) => setPassword(e.target.value)} required />
        {signup && <span className="small">At least 10 characters. Passwords found in known breaches are refused.</span>}
      </label>
      {!signup && (
        <button type="button" className="link small" style={{ justifySelf: "start" }} onClick={() => setMode("forgot")}>Forgot password?</button>
      )}
      <button className="btn primary" style={{ justifyContent: "center" }} disabled={busy}>
        {busy ? "One moment" : signup ? "Create account" : "Sign in"}
      </button>
      <p className="small">
        {signup ? "Already have an account? " : "New here? "}
        <button type="button" className="link" onClick={() => { setErr(null); setMode(signup ? "signin" : "signup"); }}>
          {signup ? "Sign in" : "Create an account"}
        </button>
      </p>
      <ErrorLine error={err} />
      <hr className="rule" />
      <p className="small muted">
        Bank or arbiter? <button type="button" className="link" onClick={() => setMode("wallet")}>Sign in with your wallet</button>
      </p>
    </form>
  );
}

/** Sign in with the wallet: the server reads the role from the deployment record. */
function WalletSignIn({ back, next }: { back?: () => void; next: string }) {
  const { data: pub } = usePublic();
  const { address, isConnected, connector } = useAccount();
  const { connectors, connectAsync } = useConnect();
  const { disconnectAsync } = useDisconnect();
  const { signMessageAsync } = useSignMessage();
  const qc = useQueryClient();
  const nav = useNavigate();
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<unknown>(null);

  const mocks = connectors.filter((c) => c.type === "mock");
  const role = pub && address ? roleOf(address, pub.roles) : null;
  const outside = !back || role === "underwriter" || role === "arbiter";

  const signIn = async () => {
    setErr(null);
    setBusy(true);
    try {
      const ch = await api.post<{ nonce: string; message: string }>("/wallet/challenge", { address });
      const signature = await signMessageAsync({ message: ch.message });
      await api.post<Me & { token: string }>("/wallet/login", { nonce: ch.nonce, signature });
      await qc.invalidateQueries();
      nav(next, { replace: true });
    } catch (e) {
      setErr(e);
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <div>
        <h1>Sign in with your wallet</h1>
        <p className="sub">
          {back
            ? "For the bank and the arbiter, who sign from outside the company. Your wallet address decides what you can do."
            : "Your wallet address decides what you can do: the owner changes settings, the finance manager approves bills, the bank reviews the reserve. Anyone else can look around."}
        </p>
      </div>

      {!isConnected ? (
        <div className="stack">
          {connectors
            .filter((c) => c.type !== "mock")
            .map((c) => (
              <button key={c.uid} className="btn" onClick={() => connectAsync({ connector: c }).catch(setErr)}>
                {connectorLabel(c)}
              </button>
            ))}
          {mocks.length > 0 && (
            <>
              <h3>Local test accounts</h3>
              {mocks.map((c, i) => (
                <button key={c.uid} className="btn" onClick={() => connectAsync({ connector: c }).catch(setErr)}>
                  {connectorLabel(c, i)}
                </button>
              ))}
            </>
          )}
        </div>
      ) : (
        <div className="stack">
          <dl className="dl">
            <dt>Wallet</dt>
            <dd className="mono">{address && shortAddr(address)}</dd>
            <dt>Connected with</dt>
            <dd>{connector?.name}</dd>
            <dt>Signs in as</dt>
            <dd>
              <b>{role ? ROLE[role] ?? role : "Viewer"}</b>
            </dd>
          </dl>
          {!outside && <p className="warn small">This wallet belongs to company staff. Staff sign in with their email.</p>}
          <div className="row">
            <button className="btn primary" disabled={busy || !outside} onClick={signIn}>
              {busy ? "Waiting for your wallet" : "Sign in"}
            </button>
            <button className="btn" onClick={() => disconnectAsync()}>
              Use another wallet
            </button>
          </div>
          <p className="note">Your wallet shows a sign-in message. Signing it costs nothing and moves no money.</p>
        </div>
      )}
      <ErrorLine error={err} />
      {back && <button className="link small" style={{ justifySelf: "start" }} onClick={back}>Back to email sign-in</button>}
    </>
  );
}
