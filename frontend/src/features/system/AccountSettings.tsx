import { FormEvent, useState } from "react";
import { api } from "../../lib/api";
import { useFeedback } from "../../components/feedback";
import { Card, Field } from "../../components/ui";

/** Change your own console password. */
export function AccountSettings() {
  const { run } = useFeedback();
  const [oldPw, setOldPw] = useState("");
  const [newPw, setNewPw] = useState("");
  const [confirmPw, setConfirmPw] = useState("");
  const mismatch = !!confirmPw && newPw !== confirmPw;

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (mismatch) return;
    const r = await run(() => api.post("/api/auth/change_password", { old_password: oldPw, new_password: newPw }), { success: "Password changed" });
    if (r) { setOldPw(""); setNewPw(""); setConfirmPw(""); }
  };

  return (
    <Card title="Change password">
      <form className="stack" style={{ gap: 14, maxWidth: 380 }} onSubmit={submit}>
        <Field label="Current password"><input className="input" type="password" autoComplete="current-password" required value={oldPw} onChange={(e) => setOldPw(e.target.value)} /></Field>
        <Field label="New password"><input className="input" type="password" autoComplete="new-password" required minLength={8} value={newPw} onChange={(e) => setNewPw(e.target.value)} /></Field>
        <Field label="Repeat new password"><input className="input" type="password" autoComplete="new-password" required value={confirmPw} onChange={(e) => setConfirmPw(e.target.value)} /></Field>
        {mismatch && <div className="down" style={{ fontSize: 12.5 }}>The new passwords do not match.</div>}
        <button className="btn primary" disabled={mismatch || !newPw}>Update password</button>
      </form>
    </Card>
  );
}
