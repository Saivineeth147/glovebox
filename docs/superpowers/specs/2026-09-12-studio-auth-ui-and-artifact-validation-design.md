# Studio auth, mission-control UI, and artifact overfit validation

Date: 2026-09-12
Status: approved, not yet implemented

Three independent changes, sequenced smallest-first so each lands on a green tree.

## Why now

A live discovery run on `openrouter:anthropic/claude-sonnet-5` (run
`discovery-20260912T075947-779ad1`) produced a capability that **passed validation and did not
work**. It hardcoded the discovery run's own data into its reusable contract:

| | committed 1.0.0 | live 1.0.1 |
|---|---|---|
| `success` conditions | `"Share Accounts"`, `"Regular Savings"` | `"Regular Savings"`, `"$1250.75"`, `"Member No. 100234"` |
| `outcomes` | `MEMBER_NOT_FOUND` (terminal) | `MEMBER_FOUND` (terminal) |
| `outputs` | `savings_balance:number`, `member_name:string` | `savings_balance:string` |

Replayed against member 100235: 1.0.1 fails `checkpoint_failed` on `text_visible: '$1250.75'`;
1.0.0 returns `18930.0` / `"Ng, Marcus"`. On the *recorded* member 1.0.1 still returns nothing,
because a terminal `MEMBER_FOUND` halts the run before the extract step.

Separately, `server.py` accepts `operator: str = "studio-user"` from the browser, so every human
takeover in the evidence log is attributed to a self-declared name.

## 1. Artifact overfit validation

**Goal:** make the artifact above impossible to produce, not merely unlikely.

The recorder knows, at record time, both the parameter values it substituted and the values it
extracted. Overfitting is therefore *checkable*, not a matter of taste.

Two rules, added to capability validation:

1. **No record-time literals in conditions.** A `success[]` or `outcomes[].detect` condition whose
   `value` contains a parameter value or an extracted output value from the recording run is
   rejected. Comparison is case-insensitive substring, and only values of **three characters or
   more** participate, so a parameter that happens to be `"1"` cannot poison every condition.
   Kills `"Member No. 100234"`.

   This alone is **not sufficient**, and the failed run proves it: its extract step targeted
   `link 'New Inquiry'`, so the extracted value was the string `"New Inquiry"`, not the balance.
   A second half is required: **a replay condition may not contain a run of two or more digits.**
   Balances, identifiers and dates are precisely what varies per input, so a condition built on
   one cannot generalize. This kills `"$1250.75"`. It is a heuristic and will also reject a
   version string such as `"Meridian Core v7.2.1"`; that false positive is accepted, because the
   error message tells the model to pick static text and version strings change too.
2. **A terminal outcome may not match the success path.** Concretely: a terminal outcome is
   rejected when its `detect.value` contains, or is contained by, any `success[].value` in the same
   artifact. `MEMBER_FOUND`'s detector `"Regular Savings $1250.75"` contains the success condition
   `"Regular Savings"`, so it is rejected. This is a structural check on the artifact and needs no
   run data.

Rule 1 needs the record-time values, which live in the run, not the artifact. So the check runs in
two places: the recorder refuses to emit such a condition (it has the values in hand), and the
validator re-checks what it can see structurally. The validator alone cannot catch every case —
that is stated rather than hidden.

**Components:** `schema/capability.py` (validation), `agent/recorder.py` (emit-time guard).
**Tests:** a recorded artifact carrying a param value in `success` is rejected; one carrying an
extracted value is rejected; a terminal outcome matching the success screen is rejected; the
committed 1.0.0 artifact still validates.
**Done when:** a fresh discovery run generalizes across members 100234, 100235 and 100999.

## 2. Studio authentication

**Goal:** the `operator` on every human action is authenticated rather than self-declared.

SQLite through stdlib `sqlite3`; `scrypt` through stdlib `hashlib`. No new dependency — consistent
with dropping `pydantic-settings` for the same reason.

| Module | Responsibility |
|---|---|
| `studio/accounts.py` | `users` table; create, fetch, verify password, set role |
| `studio/sessions.py` | `sessions` table; issue, resolve, revoke |
| `studio/routes_auth.py` | `POST /api/auth/register`, `/login`, `/logout`; `GET /api/auth/me` |
| `studio/guards.py` | `require_user`, `require_role` dependencies |

`server.py` stays under 400 lines by keeping all of this out of it.

**Data.** `users(id, email UNIQUE, password_hash, salt, role, created_at, disabled)`.
`sessions(token_sha256 PRIMARY KEY, user_id, created_at, expires_at)`. The session token is
`secrets.token_urlsafe(32)`, sent as an `httpOnly`, `SameSite=Lax` cookie and stored **only as a
SHA-256 digest**, so read access to the database cannot mint a session.

**Roles.** The first account to register becomes `admin`; every later registration becomes
`viewer`. `viewer` is read-only. `operator` may run discovery, replay and takeover. `admin` may
additionally approve capabilities and change roles. Registration is open, but not open to privilege: a new
account can read and nothing else until an admin acts.

**Gate.** A dependency on every `/api/*` route except the auth routes and a health probe. The
unknown-path catch-all at `server.py:295` must stop swallowing `/api/*`, or an unauthenticated
request to a mistyped API path returns the app shell with 200 instead of 401.

**The point.** `CommandBody.operator` is deleted. Operator identity is read from the session, so
the name recorded in `events.jsonl` for every human action is one someone authenticated as.

**Tests:** first registration is admin and second is viewer; login sets a cookie and `me` returns
the user; a revoked session is rejected; a viewer is refused takeover; an unauthenticated `/api/*`
request returns 401 rather than HTML; the recorded operator name matches the session, not the body.

## 3. Mission-control UI

**Goal:** the console should read as an instrument for watching and seizing control of a live
session, and the capture panel should stop being a mostly-empty white rectangle.

**The capture.** `BrowserFrame` renders a faithful screenshot of a light legacy app at aspect
`11/8` with `object-contain`; the app's content occupies roughly the top third, so most of the
panel is dead white. The screenshot is evidence and will not be recoloured. It will instead be
top-aligned and cropped to the region that carries content, shown larger, backed by a filmstrip of
every capture in the run, and expandable to the full untouched frame on click.

**The shell.** A top status bar carrying control lease, target reachability, model and signed-in
operator; a slim icon rail replacing the 232px sidebar; hairline rules instead of filled panels;
tabular monospace numerics; state carried by signal colour. Motion only where something is live —
a pulse that always pulses communicates nothing.

**Leverage.** `index.css` defines `.panel`, `.chip`, `.btn`, `.input`, `.label` via `@apply`, and
`tailwind.config.js` holds the palette. Retuning those two files moves every page at once; the
per-page work is layout, not restyling.

**Build.** `ui/` compiles into `src/glovebox/studio/static`, which is committed. Every UI change
requires `make ui` and the rebuilt bundle in the same commit.

**Tests:** frontend has no test harness today and adding one is out of scope; correctness is
covered by `tsc --noEmit`, the existing Python tests that assert the served shell, and a Playwright
screenshot check that the capture panel renders cropped rather than letterboxed.

## Sequencing

1. Artifact validation — smallest, and it unblocks a clean re-record.
2. Auth — self-contained; changes an existing request contract.
3. UI — largest surface; benefits from auth existing (the status bar shows the operator).

Each lands as its own commit with its tests on `env-loading-and-studio-auth`.

## Out of scope

Password reset, email verification, rate limiting on login, multi-tenant authorisation per
capability, and a frontend test harness. Each is a defensible next step; none is needed to make
the audit trail honest or the console legible.
