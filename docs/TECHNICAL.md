# Technical documentation

## 1. Architecture

* **Django 5.2** monolith with server-rendered templates and vanilla ES-module JavaScript.
  There is no build step or frontend framework.
* **PostgreSQL** in production (SQLite is fine for single-user development).
* **Short HTTP polling** (≈1 s) for teams, host and projector. Expected load is 10 phones, one
  host and one projector, which is about 12 requests per second. This is negligible for a single dyno.
* All scoring and validation is **server-side**. Clients only send *what was chosen*.

| App | Responsibility |
|---|---|
| `accounts` | e-mail + password host login (`EmailHostBackend`, staff only), rate limiting (`ratelimit.py`), `create_host` command |
| `games` | reusable content: `Experience → Mission → Question → AnswerOption`; `content.py` loads `fixtures/energy_lab.json` (idempotent; also run by migration `games/0002`) |
| `live` | runtime: sessions, teams, question runtimes, submissions, score ledger, event log, projector tokens |

The suggested `sessions/` app was named `live` instead, because `sessions` collides with
`django.contrib.sessions`.

Key modules in `live/`:

* `engine.py`: the **state machine**. Every host action goes through `perform()`.
* `services.py`: joining, slot allocation, recovery, presence, submissions, scoring, leaderboard.
* `serializers.py`: **role-scoped** state payloads (`team_state`, `display_state`, `host_state`).
* `grading.py`: answer-format validation and grading for SINGLE / TRUE_FALSE / MATCH / ORDER.
* `api.py`: JSON endpoints; `views.py`: HTML pages.

## 2. State machine

`GameSession.status` holds an explicit state, so the game never depends on scattered booleans:

```
CREATED → LOBBY ─start_game→ MISSION_INTRO ─start_question→ QUESTION_OPEN
QUESTION_OPEN ─close_question→ QUESTION_CLOSED ─reveal_answer→ ANSWER_REVEALED
ANSWER_REVEALED ─show_leaderboard→ LEADERBOARD
ANSWER_REVEALED | LEADERBOARD ─next_question→ QUESTION_OPEN (next) | MISSION_COMPLETE (last)
MISSION_COMPLETE ─next_mission→ MISSION_INTRO           (final mission: finish_game → FINISHED)
any active ─pause→ PAUSED ─resume→ previous state         (paused_from keeps the previous state)
any open ─finish_game→ FINISHED ─archive→ ARCHIVED
```

Extra transitions: `reopen_question` (CLOSED → OPEN, before reveal), `extend_time`,
`skip_question` (voids the runtime, no points), `restart_mission` (back to the mission intro;
a new runtime *attempt* is created).

`ACTION_STATES` in `engine.py` is the single table of legal source states. The dashboard's
`allowed_actions` comes from the same table, so a button is enabled exactly when the server
would accept the action. Illegal actions return `409 INVALID_TRANSITION` with a readable message.

### Double-click and concurrency protection

`perform()`:

1. locks the session row (`SELECT … FOR UPDATE`), which serializes host actions, team joins and submissions;
2. ignores a repeated `request_id`. The browser retries network failures with the same id, and
   a partial unique constraint `(session, request_id)` enforces this;
3. rejects stale clicks: progress actions carry the `expected_status` and `expected_runtime` the
   host saw. A second "NEXT QUESTION" from a double-click or a second open dashboard gets
   `409 STALE` instead of advancing twice;
4. bumps `version` and writes a `SessionEvent` (the event log).

Timestamps are taken *after* the lock is acquired, so recorded times follow the commit order.

## 3. Timing

* The server is authoritative. `QuestionRuntime.deadline` is an absolute timestamp.
* Clients estimate their clock offset from `server_time` on every poll (`ServerClock`, which
  keeps the lowest-latency sample) and render countdowns against the server deadline.
* Late answers are rejected with `TIME_UP` after `deadline + 1.5 s` grace (to absorb network latency).
* **Pause** stores `paused_remaining_ms` and clears the deadline. **Resume** sets a new deadline.
* Reaching zero never reveals or closes anything. The host stays in control.
* Default durations per mission: 20 / 25 / 35 / 30 / 60 s. The Task 4 matching question uses 45 s.
  These live in `fixtures/energy_lab.json`.

## 4. Polling protocol

| Client | Endpoint | Unchanged response |
|---|---|---|
| Team | `GET /api/live/state/?v=<version>` | `{"changed": false, "version", "server_time"}` |
| Projector | `GET /api/display/<token>/state/?etag=<etag>` | `{"changed": false, "etag", "server_time"}`. The etag also covers team presence. |
| Host | `GET /api/host/sessions/<id>/state/` | always full (one client) |

The client poller (`static/js/core.js → Poller`):

* keeps only one request in flight and schedules the next one with `setTimeout`, not `setInterval`;
* starts each client at a random 0–400 ms offset, plus 0–150 ms jitter on every poll;
* uses a 6 s `AbortController` timeout per request;
* backs off exponentially during outages (×2 per failure, max 15 s, ±25 % jitter). After two failures the UI shows "RECONNECTING…";
* polls immediately when the tab becomes visible again or the device comes back online
  (phone unlocked), and polls 3× slower while hidden;
* stops on `pagehide`. A 401/403/404 response is fatal: the team is sent back to the join page.

Presence: each team poll updates `last_seen` at most every 3 s. A team counts as offline after
10 s without a successful poll (`PRESENCE_TIMEOUT_SECONDS`). Offline teams are never removed
automatically, so their slot, score and progress are kept.

Measured query budget (tests/test_polling.py): an unchanged team poll costs ≤ 2 queries, a
full team or projector poll ≤ 10, and a full host poll ≤ 25.

## 5. Data model

| Model | Purpose / key constraints |
|---|---|
| `GameSession` | code (6 digits, `CHECK`), status, `paused_from`, `registration_open`, `version`, current mission/runtime, `expires_at`. **Unique code among sessions that are not FINISHED/ARCHIVED** (partial unique index). |
| `TeamParticipation` | one team in one session: `slot` 1–10 (`CHECK`), `name`, `name_key` (NFKC + casefold), `token_hash` (SHA-256 of the cookie credential, unique), `last_seen`, recovery-code hash and expiry. **Unique active slot per session; unique active name per session** (partial unique indexes). Removed teams keep their row for history. |
| `QuestionRuntime` | one play of a question: `attempt`, status OPEN/CLOSED/REVEALED/SKIPPED, `deadline`, `paused_remaining_ms`. Unique `(session, question, attempt)`. |
| `TeamSubmission` | **unique `(runtime, team)`**; answer JSON, `is_correct` (computed by the server), `time_fraction_left`. |
| `ScoreEvent` | append-only ledger. Leaderboards are always `SUM(points)`. **Unique `(session, team, question)` for automatic awards**, so restarting a mission or revealing twice can never double-score. Manual rows record `reason` and `created_by`. |
| `SessionEvent` | audit log, plus the host `request_id` idempotency key. |
| `DisplayToken` | hashed, expiring (12 h), session-scoped read-only projector credential. |

There is no separate `TeamSlot` table. The ten slots are the integers 1–10, enforced by the
`CHECK` constraint and the partial unique index. The free slot is chosen under the session
row lock, and the index backs it up (tested with 15 simultaneous joins on PostgreSQL).

## 6. Team identity and recovery

* Teams are **not Django users**. On join the server creates a 256-bit random token, stores
  only its SHA-256 hash, and sets it as an `HttpOnly`, `SameSite=Lax` (and `Secure` in production) cookie.
* Refresh, lost Wi-Fi or a locked phone are handled automatically: the cookie persists and the state is rebuilt from the server.
* **Lost device:** the host opens the team menu and clicks **Issue recovery code**. This gives a one-time
  6-character code that is valid for 10 minutes. On the new phone: session code → "Reconnect an existing team" →
  recovery code. The team's token is rotated, so the old device is disconnected. Knowing a team name is not enough.

## 7. Security summary

* Host login uses Django's authentication: PBKDF2 password hashing, session rotation on login, CSRF on every
  form and API POST, `never_cache` on dynamic pages, a staff-only backend, and the same error message for
  unknown e-mail and wrong password.
* Rate limits (DB cache, shared by workers) count failed attempts only: login 5 per account / 30 per IP per
  15 min; join codes 8 per browser / 60 per IP per minute. The per-IP limit is generous because a classroom
  shares one NAT address.
* Server-side authorization on every endpoint: `host_api` returns 403 JSON, team endpoints need the
  team credential, and the projector needs its token.
* Answer keys are never in team or projector payloads before reveal (tested). Teams never see other
  teams' answers.
* Team names: NFKC-normalized, trimmed, ≤ 24 characters, no control/format characters or `<`/`>`, and always
  rendered with `textContent` or Django autoescaping.
* Production: `DEBUG` off by default, the secret key must come from the environment (the app refuses
  to start without it), HTTPS redirect, secure cookies, and HSTS on this host only (not subdomains, so
  other `*.yassermansour.com` apps are unaffected), `X-Frame-Options: DENY`, nosniff and a same-origin referrer policy.

## 8. Adding another experience

Content is data. Copy `fixtures/energy_lab.json` with a new `experience.slug`, then load it with
`games.content.load_experience(...)`. `create_session` currently defaults to the `energy-lab`
experience; that is the only place to change to offer a choice. This was kept deliberately
simple rather than built into a general LMS.
