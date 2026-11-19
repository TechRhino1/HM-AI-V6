import { FormEvent, useState } from "react";
import { api } from "../../lib/api";
import { Field } from "../../components/ui";

export function LoginScreen({ onDone }: { onDone: (user: any) => void }) {
  const [mode, setMode] = useState<"login" | "register">("login");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [fullName, setFullName] = useState("");
  const [msg, setMsg] = useState<{ tone: "down" | "up"; text: string } | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setMsg(null);
    try {
      if (mode === "login") {
        // The server sets the HttpOnly session cookie; the token in the body is not stored.
        await api.post("/api/auth/login", { username: username.trim(), password });
        const v = await api.post<{ user: any }>("/api/auth/verify");
        onDone(v.user);
      } else {
        const r = await api.post<{ message?: string }>("/api/auth/register", { username: username.trim(), password, full_name: fullName.trim() });
        setMsg({ tone: "up", text: r.message || "Registered. An admin must approve the account before you can sign in." });
        setMode("login");
      }
    } catch (err: any) {
      setMsg({ tone: "down", text: err?.message || "Sign-in failed" });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div style={{ minHeight: "100%", display: "grid", placeItems: "center", padding: 16 }}>
      <form className="card" style={{ width: "min(400px, 100%)" }} onSubmit={submit}>
        <div className="card-body stack" style={{ gap: 16, padding: 28 }}>
          <div className="brand" style={{ padding: 0 }}>
            <div className="brand-mark">HM</div>
            <div>HM Trading<small>{mode === "login" ? "Sign in to the console" : "Request an account"}</small></div>
          </div>
          {msg && <div className={`alert ${msg.tone}`} role="alert">{msg.text}</div>}
          <Field label="Username">
            <input className="input" autoComplete="username" required value={username} onChange={(e) => setUsername(e.target.value)} />
          </Field>
          {mode === "register" && (
            <Field label="Full name">
              <input className="input" autoComplete="name" value={fullName} onChange={(e) => setFullName(e.target.value)} />
            </Field>
          )}
          <Field label="Password">
            <input className="input" type="password" required autoComplete={mode === "login" ? "current-password" : "new-password"}
              value={password} onChange={(e) => setPassword(e.target.value)} />
          </Field>
          <button className="btn primary lg block" disabled={busy}>{busy ? "Please wait…" : mode === "login" ? "Sign in" : "Request access"}</button>
          <button type="button" className="btn ghost block" onClick={() => { setMode(mode === "login" ? "register" : "login"); setMsg(null); }}>
            {mode === "login" ? "No account? Request access" : "Have an account? Sign in"}
          </button>
        </div>
      </form>
    </div>
  );
}
