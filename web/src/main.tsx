import React, { useMemo, type ReactNode } from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, Link, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import { WagmiProvider } from "wagmi";
import "./index.css";
import "./proto.css";
import { api, type AppState } from "./lib/api";
import { makeConfig } from "./lib/wallet";
import { Shell } from "./components/Shell";
import { Art, C } from "./components/Characters";
import Landing from "./pages/Landing";
import Login from "./pages/Login";
import Desk from "./pages/desk/Desk";
import Risk from "./pages/Risk";
import Security from "./pages/Security";
import Activity from "./pages/Activity";
import Settings from "./pages/Settings";

const queryClient = new QueryClient({ defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false } } });

function Centered({ children }: { children: ReactNode }) {
  return (
    <div className="wrap" style={{ minHeight: "80vh", display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 14, textAlign: "center" }}>
      {children}
    </div>
  );
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

/** The wallet config needs the chain from the API, so it is built after the first state call. */
function App() {
  const { data, error, refetch } = useQuery({ queryKey: ["state"], queryFn: () => api.get<AppState>("/state") });
  const config = useMemo(() => (data ? makeConfig(data.chain_id, data.rpc) : null), [data?.chain_id, data?.rpc]);
  if (error && !data)
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
  const app = (el: ReactNode) => <Shell>{el}</Shell>;
  return (
    <WagmiProvider config={config}>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<Landing />} />
          <Route path="/login" element={<Login />} />
          <Route path="/desk" element={app(<Desk />)} />
          <Route path="/risk" element={app(<Risk />)} />
          <Route path="/security" element={app(<Security />)} />
          <Route path="/activity" element={app(<Activity />)} />
          <Route path="/settings" element={app(<Settings />)} />
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
