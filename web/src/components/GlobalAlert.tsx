import { useEffect, useState } from "react";
import { API_ALERT_EVENT, type ApiAlertEvent } from "../lib/api";
import { Alert, AlertDescription, AlertTitle, AlertTriangleIcon } from "./Alert";

interface AlertItem extends ApiAlertEvent {
  id: string;
}

export function GlobalAlert() {
  const [alerts, setAlerts] = useState<AlertItem[]>([]);

  useEffect(() => {
    const handler = (e: Event) => {
      const detail = (e as CustomEvent<ApiAlertEvent>).detail;
      if (!detail) return;
      const id = `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
      const item: AlertItem = { ...detail, id };
      setAlerts((prev) => [...prev.slice(-2), item]);

      setTimeout(() => {
        setAlerts((prev) => prev.filter((a) => a.id !== id));
      }, 8000);
    };

    window.addEventListener(API_ALERT_EVENT, handler);
    return () => window.removeEventListener(API_ALERT_EVENT, handler);
  }, []);

  if (alerts.length === 0) return null;

  return (
    <div className="shadcn-alert-float-container" aria-live="assertive">
      {alerts.map((a) => (
        <Alert
          key={a.id}
          variant={a.variant ?? "destructive"}
          className="shadcn-alert-float"
          onClose={() => setAlerts((prev) => prev.filter((item) => item.id !== a.id))}
        >
          <AlertTriangleIcon />
          <div className="shadcn-alert-content">
            <AlertTitle>{a.title || "Operation Failed"}</AlertTitle>
            <AlertDescription>
              {a.message}
              {a.path && (
                <span className="mono small muted" style={{ display: "block", marginTop: 4 }}>
                  {a.path}
                </span>
              )}
            </AlertDescription>
          </div>
        </Alert>
      ))}
    </div>
  );
}
