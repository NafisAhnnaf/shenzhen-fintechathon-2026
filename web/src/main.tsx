import React, { useEffect, useMemo, type ReactNode } from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider, useQueryClient } from "@tanstack/react-query";
import { WagmiProvider } from "wagmi";
import "./styles.css";
import { SIGNED_OUT } from "./lib/api";
import { useMe, usePublic } from "./lib/hooks";
import { makeConfig } from "./lib/wallet";
import { Shell } from "./components/Shell";
import Login from "./pages/Login";
import Inbox from "./pages/Inbox";
import Bills from "./pages/Bills";
import Approvals from "./pages/Approvals";
import Payments from "./pages/Payments";
import Suppliers from "./pages/Suppliers";
import Disputes from "./pages/Disputes";
import Activity from "./pages/Activity";
import Risk from "./pages/Risk";
import Market from "./pages/Market";
import Security from "./pages/Security";
import Bank from "./pages/Bank";
import Settings from "./pages/Settings";

const queryClient = new QueryClient({ defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false } } });

function Centered({ children }: { children: ReactNode }) {
  return <div className="center"><div className="stack">{children}</div></div>;
}

/** Signed in: the desk. Otherwise: the sign-in page. */
function Gate({ children }: { children: ReactNode }) {
  const { data: me, isLoading } = useMe();
  if (isLoading) return <Centered><span className="spin" /></Centered>;
  if (!me) return <Navigate to="/login" replace />;
  return <Shell>{children}</Shell>;
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
        <h1>The desk cannot reach the agent</h1>
        <p className="muted">
          Start the API with <span className="mono">uvicorn apagent.api:app --port 8000</span> and the local chain.
        </p>
        <button className="btn primary" onClick={() => refetch()}>Try again</button>
      </Centered>
    );
  if (!config) return <Centered><span className="spin" /><p className="muted">Connecting</p></Centered>;
  const g = (el: ReactNode) => <Gate>{el}</Gate>;
  return (
    <WagmiProvider config={config}>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="/" element={<Navigate to="/bills" replace />} />
          <Route path="/inbox" element={g(<Inbox />)} />
          <Route path="/bills" element={g(<Bills />)} />
          <Route path="/approvals" element={g(<Approvals />)} />
          <Route path="/payments" element={g(<Payments />)} />
          <Route path="/suppliers" element={g(<Suppliers />)} />
          <Route path="/disputes" element={g(<Disputes />)} />
          <Route path="/activity" element={g(<Activity />)} />
          <Route path="/risk" element={g(<Risk />)} />
          <Route path="/market" element={g(<Market />)} />
          <Route path="/security" element={g(<Security />)} />
          <Route path="/bank" element={g(<Bank />)} />
          <Route path="/settings" element={g(<Settings />)} />
          <Route path="*" element={g(<Centered><h1>Page not found</h1></Centered>)} />
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
