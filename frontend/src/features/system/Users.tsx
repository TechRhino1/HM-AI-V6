import { useState } from "react";
import { api } from "../../lib/api";
import { usePoll } from "../../lib/hooks";
import { useFeedback } from "../../components/feedback";
import { dateTime } from "../../lib/format";
import { Badge, Card, Empty, ErrorNote, Loading } from "../../components/ui";

interface User { username: string; full_name?: string; role: string; status?: string; approved?: boolean; created_at?: string; last_login?: string }

/** Admin only: approve, reject or delete console users. The server enforces the ADMIN role. */
export function Users() {
  const res = usePoll<{ users: User[] }>("/api/admin/users", 0);
  const { run } = useFeedback();
  const [role, setRole] = useState<Record<string, string>>({});

  if (res.error?.includes("403") || /admin|forbidden|permission/i.test(res.error || ""))
    return <Card title="Users"><Empty title="Admins only" icon="users">Your account cannot manage users.</Empty></Card>;

  const users = res.data?.users || [];
  const isPending = (u: User) => u.status ? /pending/i.test(u.status) : u.approved === false;

  return (
    <Card title="Users" sub="Who can sign in to this console" flush>
      <ErrorNote error={res.error} onRetry={res.reload} />
      {res.loading && !res.data ? <Loading /> : !users.length ? <Empty title="No users" icon="users" /> : (
        <div className="table-wrap">
          <table className="table">
            <thead><tr><th>User</th><th>Role</th><th>Status</th><th>Last sign-in</th><th /></tr></thead>
            <tbody>
              {users.map((u) => (
                <tr key={u.username}>
                  <td><b>{u.username}</b><div className="faint" style={{ fontSize: 12 }}>{u.full_name}</div></td>
                  <td>
                    {isPending(u) ? (
                      <select className="select" style={{ height: 30, width: 120 }} value={role[u.username] || "VIEWER"}
                        onChange={(e) => setRole({ ...role, [u.username]: e.target.value })} aria-label="Role to grant">
                        <option value="VIEWER">Viewer</option><option value="TRADER">Trader</option><option value="ADMIN">Admin</option>
                      </select>
                    ) : <Badge tone={u.role === "ADMIN" ? "accent" : "flat"}>{u.role.toLowerCase()}</Badge>}
                  </td>
                  <td>{isPending(u) ? <Badge tone="warn">awaiting approval</Badge> : <Badge tone="up">active</Badge>}</td>
                  <td className="muted">{dateTime(u.last_login)}</td>
                  <td className="row" style={{ gap: 6, justifyContent: "flex-end" }}>
                    {isPending(u) && <>
                      <button className="btn sm primary" onClick={() => run(() => api.post("/api/admin/approve_user", { username: u.username, role: role[u.username] || "VIEWER" }), { success: `${u.username} approved` }).then(res.reload)}>Approve</button>
                      <button className="btn sm" onClick={() => run(() => api.post("/api/admin/reject_user", { username: u.username }), { success: `${u.username} rejected` }).then(res.reload)}>Reject</button>
                    </>}
                    <button className="btn sm danger" onClick={() => run(() => api.post("/api/admin/delete_user", { username: u.username }), {
                      success: `${u.username} deleted`,
                      confirm: { title: `Delete ${u.username}?`, danger: true, confirmLabel: "Delete user", body: "The account and its sessions are removed. This cannot be undone." },
                    }).then(res.reload)}>Delete</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}
