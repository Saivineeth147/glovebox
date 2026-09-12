import { useEffect, useState } from "react";
import { api } from "../api";
import { Panel, Empty } from "./ui";

const ROLES = ["viewer", "operator", "admin"] as const;

const WHAT_EACH_ROLE_CAN_DO: Record<string, string> = {
  viewer: "reads runs, capabilities and evidence",
  operator: "also runs discovery and replay, and takes over a live session",
  admin: "also approves capabilities and changes these roles",
};

/**
 * Who can do what, and the only way to change it.
 *
 * Every account after the first registers as a viewer, so without this the ladder has three
 * rungs and one reachable step. It sits on the policy page because that is where the rest of
 * "what is allowed" lives.
 */
export default function Operators() {
  const [users, setUsers] = useState<any[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = () =>
    api
      .users()
      .then((u) => { setUsers(u); setError(null); })
      .catch((e) => { setUsers([]); setError(e.message); });

  useEffect(() => { load(); }, []);

  const change = async (email: string, role: string) => {
    try {
      await api.setRole(email, role);
      load();
    } catch (e: any) {
      setError(e.message);
    }
  };

  if (users === null) return null;

  return (
    <Panel title="Operators" padded={false}>
      {error && <p className="px-4 py-3 text-[13px] text-attention-300">{error}</p>}
      {!error && users.length === 0 && <Empty>No accounts yet.</Empty>}
      {users.map((user) => (
        <div
          key={user.email}
          className="flex items-center gap-3 px-4 py-2.5 border-b border-ink-800 last:border-0"
        >
          <div className="min-w-0 flex-1">
            <div className="text-[13px] text-ink-100 truncate">{user.email}</div>
            <div className="hint">{WHAT_EACH_ROLE_CAN_DO[user.role]}</div>
          </div>
          <select
            className="input !w-auto !py-1"
            value={user.role}
            onChange={(e) => change(user.email, e.target.value)}
          >
            {ROLES.map((role) => (
              <option key={role} value={role}>{role}</option>
            ))}
          </select>
        </div>
      ))}
    </Panel>
  );
}
