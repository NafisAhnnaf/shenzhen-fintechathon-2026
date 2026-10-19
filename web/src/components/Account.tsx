import { useQueryClient } from "@tanstack/react-query";
import QRCode from "qrcode";
import { useEffect, useState, type FormEvent } from "react";
import { useAccount, useConnect, useDisconnect, useSignMessage } from "wagmi";
import { api } from "../lib/api";
import { auth } from "../lib/auth";
import { ROLE, shortAddr } from "../lib/format";
import { useMe } from "../lib/hooks";
import { connectorLabel } from "../lib/wallet";
import { ErrorLine, Tag } from "./ui";

/** Settings → My account: password, two-step sign-in, and the wallet this person signs payments with. */
export default function Account() {
  const { data: me } = useMe();
  if (!me) return null;
  if (me.kind !== "account")
    return (
      <div className="card pad">
        <p>You signed in with the wallet <span className="mono">{me.address && shortAddr(me.address)}</span>. There is no password or two-step sign-in to manage.</p>
      </div>
    );
  return (
    <div className="stack">
      <div className="card pad stack">
        <h2>{me.name}</h2>
        <dl className="dl">
          <dt>Email</dt><dd>{me.email}</dd>
          <dt>Role here</dt><dd>{me.label}</dd>
        </dl>
      </div>
      <div className="split even">
        <TwoFactor on={!!me.two_factor} />
        <Password />
      </div>
      <SigningWallet />
    </div>
  );
}

function TwoFactor({ on }: { on: boolean }) {
  const qc = useQueryClient();
  const [pw, setPw] = useState("");
  const [setup, setSetup] = useState<{ uri: string; codes: string[]; qr: string } | null>(null);
  const [code, setCode] = useState("");
  const [err, setErr] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");

  const step = (fn: () => Promise<void>) => async (e: FormEvent) => {
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
  const start = step(async () => {
    const r = await auth.enableTwoFactor(pw);
    setSetup({ uri: r.totpURI, codes: r.backupCodes, qr: await QRCode.toDataURL(r.totpURI, { margin: 1, width: 168 }) });
    setPw("");
  });
  const confirm = step(async () => {
    await auth.verifyTotp(code.replace(/\s/g, ""), false);
    setSetup(null);
    setCode("");
    setMsg("Two-step sign-in is on. Keep the backup codes somewhere safe.");
    await qc.invalidateQueries({ queryKey: ["me"] });
    await qc.invalidateQueries({ queryKey: ["team"] });
  });
  const turnOff = step(async () => {
    await auth.disableTwoFactor(pw);
    setPw("");
    setMsg("Two-step sign-in is off.");
    await qc.invalidateQueries({ queryKey: ["me"] });
    await qc.invalidateQueries({ queryKey: ["team"] });
  });
  const secret = setup ? new URL(setup.uri).searchParams.get("secret") : null;

  return (
    <div className="card pad stack">
      <div className="between">
        <h2>Two-step sign-in</h2>
        {on ? <Tag tone="ok">On</Tag> : <Tag tone="idle">Off</Tag>}
      </div>
      <p className="note">After your password, the desk asks for a code from an authenticator app (Google Authenticator, Microsoft Authenticator, 1Password).</p>
      {msg && <p className="ok small">{msg}</p>}
      {setup ? (
        <form className="stack" onSubmit={confirm}>
          <p>Scan this with your authenticator app, then enter the code it shows.</p>
          <img className="qr" src={setup.qr} alt="Authenticator setup code" />
          {secret && <p className="small muted">Or type this key: <span className="mono">{secret}</span></p>}
          <h3>Backup codes</h3>
          <p className="note">Each works once if you lose your phone. Save them now; they are not shown again.</p>
          <div className="codes">{setup.codes.map((c) => <span key={c}>{c}</span>)}</div>
          <label className="lbl">
            Code from the app
            <input className="field" inputMode="numeric" autoComplete="one-time-code" value={code} onChange={(e) => setCode(e.target.value)} required />
          </label>
          <div className="row">
            <button className="btn primary" disabled={busy}>Turn on</button>
            <button type="button" className="btn" onClick={() => setSetup(null)}>Cancel</button>
          </div>
        </form>
      ) : (
        <form className="row" style={{ alignItems: "end", flexWrap: "wrap" }} onSubmit={on ? turnOff : start}>
          <label className="lbl" style={{ flex: "1 1 200px" }}>
            Your password
            <input className="field" type="password" autoComplete="current-password" value={pw} onChange={(e) => setPw(e.target.value)} required />
          </label>
          <button className={`btn ${on ? "danger" : "primary"}`} disabled={busy}>{on ? "Turn off" : "Set up"}</button>
        </form>
      )}
      <ErrorLine error={err} />
    </div>
  );
}

function Password() {
  const [cur, setCur] = useState("");
  const [pw, setPw] = useState("");
  const [err, setErr] = useState<unknown>(null);
  const [done, setDone] = useState(false);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setErr(null);
    setDone(false);
    try {
      await auth.changePassword(cur, pw);
      setCur("");
      setPw("");
      setDone(true);
    } catch (x) {
      setErr(x);
    }
  };
  return (
    <form className="card pad stack" onSubmit={submit}>
      <h2>Password</h2>
      <label className="lbl">
        Current password
        <input className="field" type="password" autoComplete="current-password" value={cur} onChange={(e) => setCur(e.target.value)} required />
      </label>
      <label className="lbl">
        New password
        <input className="field" type="password" autoComplete="new-password" minLength={10} value={pw} onChange={(e) => setPw(e.target.value)} required />
      </label>
      <div className="row">
        <button className="btn">Change password</button>
        {done && <span className="ok small">Changed. Your other sessions were signed out.</span>}
      </div>
      <ErrorLine error={err} />
    </form>
  );
}

function SigningWallet() {
  const { data: me } = useMe();
  const qc = useQueryClient();
  const { address, isConnected } = useAccount();
  const { connectors, connectAsync } = useConnect();
  const { disconnectAsync } = useDisconnect();
  const { signMessageAsync } = useSignMessage();
  const [err, setErr] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const [choose, setChoose] = useState(false);
  useEffect(() => setErr(null), [address]);
  if (!me) return null;
  const mocks = connectors.filter((c) => c.type === "mock");
  const signs = me.role === "owner" || me.role === "approver";

  const link = async () => {
    setErr(null);
    setBusy(true);
    try {
      const ch = await api.post<{ nonce: string; message: string }>("/me/wallet/challenge", { address });
      const signature = await signMessageAsync({ message: ch.message });
      await api.post("/me/wallet", { nonce: ch.nonce, signature });
      setChoose(false);
      await qc.invalidateQueries();
    } catch (x) {
      setErr(x);
    } finally {
      setBusy(false);
    }
  };
  const unlink = async () => {
    await api.post("/me/wallet/unlink");
    await qc.invalidateQueries();
  };

  return (
    <div className="card pad stack">
      <h2>Signing wallet</h2>
      <p className="note">
        {signs
          ? "Approvals and setting changes are signed in your own wallet; the desk never holds your key. Link the wallet you sign with so the desk asks that wallet."
          : "Your role does not sign on chain. You can still link a wallet; it gives you no extra rights."}
      </p>
      {me.address ? (
        <dl className="dl">
          <dt>Linked wallet</dt><dd className="mono">{me.address}</dd>
          <dt>On chain it is</dt>
          <dd>{me.signs_as && me.signs_as !== "viewer" ? <span className="ok">{ROLE[me.signs_as] ?? me.signs_as}</span> : "Not a signer for this company"}</dd>
        </dl>
      ) : (
        <p className="muted">No wallet linked.</p>
      )}
      {signs && me.expected_wallet && me.address?.toLowerCase() !== me.expected_wallet.toLowerCase() && (
        <p className="warn small">The {me.label} signer for this company is <span className="mono">{shortAddr(me.expected_wallet)}</span>. Link that wallet to approve and sign.</p>
      )}
      {!choose ? (
        <div className="row">
          <button className="btn" onClick={() => setChoose(true)}>{me.address ? "Link another wallet" : "Link a wallet"}</button>
          {me.address && <button className="btn" onClick={unlink}>Unlink</button>}
        </div>
      ) : !isConnected ? (
        <div className="stack">
          {connectors.filter((c) => c.type !== "mock").map((c) => (
            <button key={c.uid} className="btn" onClick={() => connectAsync({ connector: c }).catch(setErr)}>{connectorLabel(c)}</button>
          ))}
          {mocks.length > 0 && (
            <>
              <h3>Local test accounts</h3>
              {mocks.map((c, i) => (
                <button key={c.uid} className="btn" onClick={() => connectAsync({ connector: c }).catch(setErr)}>{connectorLabel(c, i)}</button>
              ))}
            </>
          )}
          <button className="link small" style={{ justifySelf: "start" }} onClick={() => setChoose(false)}>Cancel</button>
        </div>
      ) : (
        <div className="stack">
          <p>Connected: <span className="mono">{address}</span></p>
          <div className="row">
            <button className="btn primary" disabled={busy} onClick={link}>{busy ? "Waiting for your wallet" : "Sign to link this wallet"}</button>
            <button className="btn" onClick={() => disconnectAsync()}>Use another wallet</button>
            <button className="btn" onClick={() => setChoose(false)}>Cancel</button>
          </div>
          <p className="note">Signing the message proves you hold the wallet. It costs nothing and moves no money.</p>
        </div>
      )}
      <ErrorLine error={err} />
    </div>
  );
}
