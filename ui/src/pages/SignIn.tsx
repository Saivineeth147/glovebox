import { FormEvent, useState } from "react";
import { api } from "../api";

/**
 * The way in. Registration is open because the first account is the only one that gets
 * admin — everyone after it can read and nothing else until an admin raises them — so the
 * form says that plainly rather than hiding it behind a separate invite flow.
 */
export default function SignIn({ onSignedIn }: { onSignedIn: (u: any) => void }) {
  const [isRegistering, setIsRegistering] = useState(false);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      onSignedIn(await (isRegistering ? api.register : api.signIn)(email, password));
    } catch (e: any) {
      setError(e.message);
      setBusy(false);
    }
  };

  return (
    <div className="h-full grid place-items-center px-4">
      <div className="w-full max-w-[380px]">
        <div className="flex items-baseline gap-2 mb-5">
          <span className="text-[15px] font-semibold tracking-[0.14em] text-ink-100">GLOVEBOX</span>
          <span className="hint">Studio</span>
        </div>

        <form onSubmit={submit} className="panel p-5">
          <h1 className="text-[15px] font-semibold text-ink-100">
            {isRegistering ? "Create an account" : "Sign in"}
          </h1>
          <p className="hint mt-1.5">
            {isRegistering
              ? "The first account created becomes the administrator. Later accounts can read runs and capabilities until an administrator gives them more."
              : "Operating a run and approving a capability are recorded against your account."}
          </p>

          <label className="block mt-4">
            <span className="label">Email</span>
            <input
              className="input mt-1.5"
              type="email"
              autoComplete="username"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
          </label>

          <label className="block mt-3">
            <span className="label">Password</span>
            <input
              className="input mt-1.5"
              type="password"
              autoComplete={isRegistering ? "new-password" : "current-password"}
              required
              minLength={isRegistering ? 12 : undefined}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
            {isRegistering && <span className="hint mt-1 block">At least 12 characters.</span>}
          </label>

          {error && <p className="mt-3 text-[13px] text-rose-300">{error}</p>}

          <button className="btn btn-primary w-full justify-center mt-4" disabled={busy}>
            {busy ? "Working…" : isRegistering ? "Create account" : "Sign in"}
          </button>

          <button
            type="button"
            className="mt-3 w-full text-[12px] text-ink-400 hover:text-ink-200"
            onClick={() => {
              setIsRegistering(!isRegistering);
              setError(null);
            }}
          >
            {isRegistering ? "I already have an account" : "Create the first account"}
          </button>
        </form>
      </div>
    </div>
  );
}
