import React, { useEffect, useMemo, type ReactNode } from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, Link, Navigate, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider, useQueryClient } from "@tanstack/react-query";
import { WagmiProvider } from "wagmi";
// Our app (purple design, Tailwind) and, scoped under .classic, the team's other screens.
import "./purple/index.css";
import "./purple/proto.css";
import "./styles.css";
import { SIGNED_OUT } from "./lib/api";
import { useMe, usePublic } from "./lib/hooks";
import { makeConfig } from "./lib/wallet";
import { Art, C } from "./purple/components/Characters";
import { Shell } from "./purple/components/Shell";
import Landing from "./pages/Landing";
import Login from "./purple/pages/Login";
import Desk from "./purple/pages/desk/Desk";
import Risk from "./purple/pages/Risk";
import Security from "./purple/pages/Security";
import Activity from "./purple/pages/Activity";
import Settings from "./purple/pages/Settings";
import Welcome, { AcceptInvitation, ResetPassword } from "./pages/Welcome";
import Inbox from "./pages/Inbox";
import Bills from "./pages/Bills";
import Approvals from "./pages/Approvals";
import Payments from "./pages/Payments";
import Suppliers from "./pages/Suppliers";
import Disputes from "./pages/Disputes";
import Market from "./pages/Market";
import Controls from "./pages/Controls";
import Bank from "./pages/Bank";

const queryClient = new QueryClient({ defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false } } });

function Centered({ children }: { children: ReactNode }) {
  return (
    <div className="wrap" style={{ minHeight: "80vh", display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 14, textAlign: "center" }}>
      {children}
    </div>
  );
}

/** The team's screens: their markup and stylesheet, inside our shell. */
function Classic({ children }: { children: ReactNode }) {
  return (
    <div className="classic classic-in-shell">
      <div className="page">{children}</div>
    </div>
  );
}

/** Signed in with a company open: the desk. Signed in without one: the welcome page. Otherwise: sign-in. */
function Gate({ children }: { children: ReactNode }) {
  const { data: me, isLoading } = useMe();
  if (isLoading)
    return (
      <Centered>
        <span className="spin dark" />
      </Centered>
    );
  if (!me) return <Navigate to={`/login?next=${encodeURIComponent(window.location.pathname + window.location.search)}`} replace />;
  if (me.role === "none") return <Navigate to="/welcome" replace />;
  return <Shell>{children}</Shell>;
}

function NotFound() {
  return (
    <Centered>
      <Art html={C.clerk("sheepish", 140)} />
      <h1 style={{ fontSize: 34 }}>Page not found</h1>
      <p className="muted">That page doesn't exist on the desk.</p>
      <Link className="btn btn-primary" to="/desk">
        Back to the desk
      </Link>
    </Centered>
  );
}

function App() {
  const { data: pub, error, refetch } = usePublic();
  const qc = useQueryClient();
  useEffect(() => {
    const out = () => qc.invalidateQueries({ queryKey: ["me"] });
    window.addEventListener(SIGNED_OUT, out);
    return () => window.removeEventListener(SIGNED_OUT, out);
  }, [qc]);
  const config = useMemo(() => (pub ? makeConfig(pub.chain_id, pub.rpc) : null), [pub?.chain_id, pub?.rpc]);
  if (error && !pub)
    return (
      <Centered>
        <Art html={C.clerk("think", 140)} />
        <h1 style={{ fontSize: 30 }}>The desk can't reach the agent</h1>
        <p className="muted" style={{ maxWidth: "60ch" }}>
          Start the API with <span className="mono">uvicorn apagent.api:app --port 8000</span>, and a local chain if you use one.
        </p>
        <button className="btn btn-primary" onClick={() => refetch()}>
          Try again
        </button>
      </Centered>
    );
  if (!config)
    return (
      <Centered>
        <span className="spin dark" />
        <p className="muted">Connecting to the agent</p>
      </Centered>
    );
  const app = (el: ReactNode) => <Gate>{el}</Gate>;
  const classic = (el: ReactNode) => <Gate><Classic>{el}</Classic></Gate>;
  const plain = (el: ReactNode) => <div className="classic">{el}</div>;
  return (
    <WagmiProvider config={config}>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<Landing />} />
          <Route path="/login" element={<Login />} />
          <Route path="/welcome" element={plain(<Welcome />)} />
          <Route path="/accept-invitation/:id" element={plain(<AcceptInvitation />)} />
          <Route path="/reset-password" element={plain(<ResetPassword />)} />
          <Route path="/desk" element={app(<Desk />)} />
          <Route path="/activity" element={app(<Activity />)} />
          <Route path="/risk" element={app(<Risk />)} />
          <Route path="/security" element={app(<Security />)} />
          <Route path="/settings" element={app(<Settings />)} />
          <Route path="/approvals" element={classic(<Approvals />)} />
          <Route path="/bills" element={classic(<Bills />)} />
          <Route path="/payments" element={classic(<Payments />)} />
          <Route path="/suppliers" element={classic(<Suppliers />)} />
          <Route path="/disputes" element={classic(<Disputes />)} />
          <Route path="/market" element={classic(<Market />)} />
          <Route path="/bank" element={classic(<Bank />)} />
          <Route path="/inbox" element={classic(<Inbox />)} />
          <Route path="/controls" element={classic(<Controls />)} />
          <Route path="*" element={<NotFound />} />
        </Routes>
      </BrowserRouter>
    </WagmiProvider>
  );
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>
  </React.StrictMode>,
);
