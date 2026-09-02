import { type FormEvent, useCallback, useEffect, useRef, useState } from "react";

import { api } from "./api";
import { ChronosMark, StatusSquare } from "./ui";

type Reachability = "checking" | "available" | "unavailable";

export default function Login({ onAuthenticated }: { onAuthenticated: () => void }) {
  const [accessKey, setAccessKey] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const [reachability, setReachability] = useState<Reachability>("checking");
  const accessKeyRef = useRef<HTMLInputElement>(null);

  const checkReachability = useCallback(async () => {
    try {
      const result = await api<{ status: string }>("/api/public/reachability");
      setReachability(result.status === "available" ? "available" : "unavailable");
    } catch {
      setReachability("unavailable");
    }
  }, []);

  useEffect(() => {
    accessKeyRef.current?.focus();
    void checkReachability();
    const timer = window.setInterval(() => void checkReachability(), 15_000);
    return () => window.clearInterval(timer);
  }, [checkReachability]);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!accessKey || pending) return;
    setPending(true);
    setError("");
    try {
      await api("/api/auth/login", {
        method: "POST",
        body: JSON.stringify({ access_key: accessKey }),
      });
      setAccessKey("");
      onAuthenticated();
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Access denied.");
      window.setTimeout(() => accessKeyRef.current?.focus(), 0);
    } finally {
      setPending(false);
    }
  };

  return (
    <main className="login-view">
      <div className="login-composition">
        <div className="login-brand" aria-label="Chronos">
          <span>Chronos</span>
          <ChronosMark compact />
        </div>
        <section className="login-panel" aria-label="Enter Chronos">
          <div className={`availability availability-${reachability}`} role="status">
            <span>Service reachability</span>
            <StatusSquare state={reachability === "available" ? "success" : reachability === "unavailable" ? "danger" : "neutral"} />
          </div>
          <form onSubmit={submit}>
            <input
              ref={accessKeyRef}
              aria-label="Access Key"
              type="password"
              autoComplete="current-password"
              placeholder="Access Key..."
              value={accessKey}
              onChange={(event) => setAccessKey(event.target.value)}
              required
            />
            {error && <p className="login-error" role="alert">{error}</p>}
            <button type="submit" disabled={!accessKey || pending} data-smart-hover>
              {pending ? "Entering..." : "Enter service"}
            </button>
          </form>
        </section>
      </div>
    </main>
  );
}
