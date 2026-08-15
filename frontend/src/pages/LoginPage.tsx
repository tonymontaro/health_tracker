import { type FormEvent, useState } from "react";
import { Navigate, useNavigate } from "react-router-dom";
import { api, setCsrf } from "../api/client";
import { useAuth } from "../components/auth";

export function LoginPage() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);
  const { session, refresh } = useAuth();
  const navigate = useNavigate();

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError("");
    setPending(true);
    try {
      const session = await api<{ csrf_token: string }>("/auth/login", {
        method: "POST",
        body: JSON.stringify({ email, password }),
      });
      setCsrf(session.csrf_token);
      await refresh();
      navigate("/today/exercise");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Login failed");
    } finally {
      setPending(false);
    }
  }

  if (session) return <Navigate to="/today/exercise" replace />;

  return (
    <main className="login-page">
      <form className="login-card" onSubmit={submit}>
        <div className="brand-mark large">HA</div>
        <p className="eyebrow">Personal field notes</p>
        <h1>Welcome<br /><em>back.</em></h1>
        <p className="login-intro">Your daily training, food, and health record is ready when you are.</p>
        <label>Email<input autoComplete="username" type="email" autoFocus value={email} onChange={(event) => setEmail(event.target.value)} /></label>
        <label>Password<input autoComplete="current-password" type="password" value={password} onChange={(event) => setPassword(event.target.value)} /></label>
        {error && <p className="error" role="alert">{error}</p>}
        <button className="primary" type="submit" disabled={pending || !email.trim() || password.length < 8}>{pending ? "Signing in..." : "Open today's exercise"} {!pending && <span aria-hidden="true">→</span>}</button>
      </form>
    </main>
  );
}
