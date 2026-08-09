import { type FormEvent, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, setCsrf } from "../api/client";
import { useAuth } from "../components/auth";

export function LoginPage() {
  const [email, setEmail] = useState("owner@localhost");
  const [password, setPassword] = useState("change-me-now");
  const [error, setError] = useState("");
  const { refresh } = useAuth();
  const navigate = useNavigate();

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError("");
    try {
      const session = await api<{ csrf_token: string }>("/auth/login", {
        method: "POST",
        body: JSON.stringify({ email, password }),
      });
      setCsrf(session.csrf_token);
      await refresh();
      navigate("/today");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Login failed");
    }
  }

  return (
    <main className="login-page">
      <form className="login-card" onSubmit={submit}>
        <div className="brand-mark large">HA</div>
        <p className="eyebrow">Personal health autopilot</p>
        <h1>Welcome back</h1>
        <label>Email<input type="email" value={email} onChange={(event) => setEmail(event.target.value)} /></label>
        <label>Password<input type="password" value={password} onChange={(event) => setPassword(event.target.value)} /></label>
        {error && <p className="error">{error}</p>}
        <button className="primary" type="submit">Open today</button>
      </form>
    </main>
  );
}
