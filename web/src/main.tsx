import React, { useMemo } from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import { WagmiProvider } from "wagmi";
import "./index.css";
import { api, type AppState } from "./lib/api";
import { makeConfig } from "./lib/wallet";
import { Shell } from "./components/Shell";
import Desk from "./pages/desk/Desk";
import Risk from "./pages/Risk";
import Security from "./pages/Security";
import Activity from "./pages/Activity";

const queryClient = new QueryClient({ defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false } } });

/** The wallet config needs the chain from the API, so it is built after the first state call. */
function App() {
  const { data, error } = useQuery({ queryKey: ["state"], queryFn: () => api.get<AppState>("/state") });
  const config = useMemo(() => (data ? makeConfig(data.chain_id, data.rpc) : null), [data?.chain_id, data?.rpc]);
  if (error)
    return (
      <div className="mx-auto max-w-[60ch] px-6 py-16">
        <h1 className="text-xl font-medium">The desk cannot reach the agent</h1>
        <p className="mt-2 text-muted">Start the API with uvicorn apagent.api:app --port 8000, and a local chain if you use one. {String(error)}</p>
      </div>
    );
  if (!config) return <div className="px-6 py-16 text-muted">Connecting to the agent</div>;
  return (
    <WagmiProvider config={config}>
      <BrowserRouter>
        <Shell>
          <Routes>
            <Route path="/" element={<Desk />} />
            <Route path="/risk" element={<Risk />} />
            <Route path="/security" element={<Security />} />
            <Route path="/activity" element={<Activity />} />
          </Routes>
        </Shell>
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
