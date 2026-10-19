import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAccount, useConnect, useDisconnect, useSignMessage } from "wagmi";
import { api, type Me } from "../lib/api";
import { ROLE, shortAddr } from "../lib/format";
import { usePublic } from "../lib/hooks";
import { connectorLabel, roleOf } from "../lib/wallet";
import { ErrorLine } from "../components/ui";

/** Sign in with the wallet. The server reads the role from the deployment record; nobody types a password. */
export default function Login() {
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

  const signIn = async () => {
    setErr(null);
    setBusy(true);
    try {
      const ch = await api.post<{ nonce: string; message: string }>("/auth/challenge", { address });
      const signature = await signMessageAsync({ message: ch.message });
      await api.post<Me & { token: string }>("/auth/login", { nonce: ch.nonce, signature });
      await qc.invalidateQueries();
      nav("/bills");
    } catch (e) {
      setErr(e);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="center">
      <div className="login card pad">
        <div className="brand" style={{ padding: 0 }}>
          <div className="mark">H</div>
          <div>
            <b>{pub?.company.replace(" (fictional)", "") ?? "Payables desk"}</b>
            <span>Accounts payable</span>
          </div>
        </div>
        <div>
          <h1>Sign in with your wallet</h1>
          <p className="sub">
            Your wallet address decides what you can do: the owner changes settings, the finance manager approves bills, the bank reviews
            the reserve. Anyone else can look around.
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
            <div className="row">
              <button className="btn primary" disabled={busy} onClick={signIn}>
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
      </div>
    </div>
  );
}
