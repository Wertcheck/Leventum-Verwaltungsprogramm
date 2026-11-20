import { useState, type FormEvent } from "react";
import { api, ApiError, type User } from "../lib/api";
import { Card } from "../components/ui";

export default function Auth({ setup, onDone }: { setup: boolean; onDone: (u: User) => void }) {
  const [username, setUsername] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!username.trim()) { setError("Bitte füllen Sie das Pflichtfeld „Benutzername“ aus."); return; }
    if (!password) { setError("Bitte füllen Sie das Pflichtfeld „Passwort“ aus."); return; }
    setError(""); setBusy(true);
    try {
      const u = await api<User>(setup ? "/auth/setup" : "/auth/login", { method: "POST", json: setup ? { username, password, display_name: displayName } : { username, password } });
      onDone(u);
    } catch (err) { setError(err instanceof ApiError ? err.message : "Verbindung zum Server fehlgeschlagen."); }
    finally { setBusy(false); }
  }
  return (
    <div className="auth-wrap">
      <Card className="auth-card">
        <img src="/logo.png" alt="Leventum Real Estate" />
        <h2>{setup ? "Ersteinrichtung" : "Anmelden"}</h2>
        {setup && <p className="muted">Legen Sie den Administrator-Zugang an. Es gibt kein Standardpasswort. Mindestens 12 Zeichen.</p>}
        <form onSubmit={submit} noValidate style={{ display: "contents" }}>
          <label>Benutzername<input className="field" value={username} onChange={(e) => setUsername(e.target.value)} autoFocus autoComplete="username" required /></label>
          {setup && <label>Anzeigename<input className="field" value={displayName} onChange={(e) => setDisplayName(e.target.value)} /></label>}
          <label>Passwort<input className="field" type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete={setup ? "new-password" : "current-password"} required /></label>
          {error && <div className="alert err" role="alert">{error}</div>}
          <button className="btn primary" disabled={busy}>{setup ? "Administrator anlegen" : "Anmelden"}</button>
        </form>
      </Card>
    </div>
  );
}
