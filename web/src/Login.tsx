import { type FormEvent, useEffect, useRef, useState } from "react";

import { api } from "./api";


export default function Login({ onAuthenticated }: { onAuthenticated: () => void }) {
  const [login, setLogin] = useState("");
  const [password, setPassword] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const loginRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    loginRef.current?.focus();
  }, []);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!login.trim() || !password || pending) return;
    setPending(true);
    setError("");
    try {
      await api("/api/auth/login", {
        method: "POST",
        body: JSON.stringify({ username: login.trim(), password }),
      });
      onAuthenticated();
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Sign-in failed.");
      window.setTimeout(() => loginRef.current?.focus(), 0);
    } finally {
      setPending(false);
    }
  };

  return (
    <main className="login-view">
      <section className="login-panel">
        <header>
          <h1 aria-label="CHRONOS">
            {"CHRONOS".split("").map((letter, index) => <span key={`${letter}-${index}`}>{letter}</span>)}
          </h1>
          <div className="availability">
            <span aria-hidden="true" />
            AVAILABLE
          </div>
        </header>
        <form onSubmit={submit}>
          <input
            ref={loginRef}
            aria-label="Login"
            autoComplete="username"
            placeholder="Login"
            value={login}
            onChange={(event) => setLogin(event.target.value)}
            required
          />
          <input
            aria-label="Password"
            type="password"
            autoComplete="current-password"
            placeholder="Password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            required
          />
          {error && <p className="login-error" role="alert">{error}</p>}
          <button type="submit" disabled={!login.trim() || !password || pending} data-smart-hover>
            {pending ? "Signing in..." : "Sign in"}
          </button>
        </form>
      </section>
    </main>
  );
}
