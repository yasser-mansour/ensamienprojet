# Test report

Environment: Claude Code cloud container · Python 3.13 · Django 5.2.18 · **PostgreSQL 16**
(local, in-container) · Chromium (Playwright 1.63) · gunicorn 26 with 3 workers × 4 threads in
production mode (`DEBUG=0`, hashed/compressed static files, database cache).
Date: 2026-10-09.

## 1. Automated test suite: `python manage.py test tests`

| Database | Result |
|---|---|
| PostgreSQL 16 | **116 tests, all passed** |
| SQLite (dev default) | 116 tests: 110 passed, 6 skipped (the threaded concurrency tests need PostgreSQL row locks) |

Coverage by requirement:

| Area | Tests (file) |
|---|---|
| Host authentication, generic errors, rate limiting, fail-open cache, spoofed X-Forwarded-For, open-redirect, CSRF, logout | `test_auth.py` |
| Unauthorized host access (anonymous, team cookie, non-staff user) to pages, APIs and projector | `test_auth.py` |
| Session creation, six-digit random codes, collision retry, code reuse after finish, history preserved | `test_joining.py` |
| Invalid / expired / closed-registration / full codes, join rate limit, registration closing mid-join | `test_joining.py` |
| Team names: empty, too long, HTML/control characters, whitespace, case- and width-insensitive duplicates, escaping | `test_joining.py` |
| Capacity (10 slots, 11th rejected), slot reopening after removal | `test_joining.py` |
| Reconnect with cookie, forged cookie, recovery code (single use, expiry, old device revoked, name not enough) | `test_joining.py` |
| State machine: every main transition, invalid transitions, stale double-clicks, idempotent request ids, pause/resume timer freeze, extend, reopen, skip, next mission, restart mission (no double award), finish, archive, audit log, CSRF on the action API | `test_engine.py` |
| Submissions: accept, idempotent retry, change rejected, late (server clock), grace window, closed, stale, invalid formats, client-sent score ignored, removed team | `test_scoring.py` |
| Scoring: 100 / 0 / 300 (Final Boss), matching all-or-nothing, award only at reveal, no double reveal, manual adjustments with reason and admin, leaderboard ties, speed bonus | `test_scoring.py` |
| Polling: version minimal responses, answer key hidden from teams and projector until reveal, other teams' answers hidden, projector etag, display token expiry, host/projector/team synchronization, presence | `test_polling.py` |
| Query budgets: unchanged team poll ≤ 2 queries; full team / projector poll ≤ 10; host poll ≤ 25 | `test_polling.py` |
| **Concurrency (real threads, PostgreSQL)**: 15 simultaneous joins → exactly slots 1–10; same-name race; 8 duplicate simultaneous submissions → 1 stored; submissions racing a close; 5 simultaneous host clicks → applied once; concurrent reveals → scored once | `test_concurrency.py` |
| Content: 5 missions / 26 questions, every answer key valid, Final Boss order and 300 EP, textbook T/F key, Task 4 key, idempotent reload | `test_content.py` |

## 2. Browser end-to-end test: `tools/e2e.py`

Real Chromium, against the production-mode gunicorn server. The host runs at 1440×900 and the
projector in a separate window at 1920×1080. Ten team phones run as separate browser contexts
at 390×844 with touch and mobile emulation.

**Result: PASSED (48 explicit checks, plus Playwright waits on every state change).** The scenario:

1. Host sign-in fails with a wrong password, then succeeds.
2. Create a session; the six-digit code is shown on the dashboard and the projector.
3. An invalid code is rejected on a phone.
4. 10 teams join through the real UI; each appears on the projector (10 / 10).
5. An 11th phone gets **SESSION FULL**.
6. The host removes 2 teams through the team menu and confirmation dialog. Their phones show "Team removed"; the projector shows 8 / 10.
7. A duplicate name (`"  alpha "`) is rejected.
8. **START GAME** closes registration; all phones switch to Mission 01.
9. All **5 missions / 26 questions** are played. Teams answer through the real controls: single
   choice, true/false, the Task 4 matching grid, Final Boss by tapping (6 teams) and by
   **pointer drag-and-drop** (1 team). One team skips one question per mission.
10. During Q1 the phone's connection indicator and **ticking countdown** are checked. One captain
    **reloads mid-question** and the answer receipt is still there.
11. During Mission 02 the game is **paused** (overlay on phones and projector; timer frozen for 1.5 s, verified) and then resumed.
12. Close → reveal on every question. **Every team's score is compared with the expected total
    computed from the answer key after every reveal.** A manual +50 EP bonus with a reason is
    included and checked.
13. Leaderboards, mission completion, Final Boss reveal animation, **FINISH GAME**, then the winner screen.
14. A team phone calling the host action API gets 403.
15. The session report lists every team, every question and the manual adjustment; the history page lists the session.

Screenshots from this run are in [`docs/screenshots/`](screenshots/).

Visual QA of those screenshots found and fixed: the projector lobby overflowing with 10 teams,
the QR rendering smaller than its box, the empty band under projector questions, the Final Boss
layout taller than a phone screen, the final-screen leaderboard overflowing, the sequence arrows
hidden under cards, and report cells wrapping.

Bugs found by the browser/production runs and fixed (each has a regression check):

* Whole-code autofill/paste was truncated by `maxlength="1"` on the digit boxes.
* The host team table was rebuilt every second, so clicks could land on detached buttons. It now re-renders only on change.
* `SELECT … FOR UPDATE` on a nullable outer join failed on PostgreSQL. Only the session row is locked now.
* The phone countdown did not tick until the next state change; the "CONNECTING…" label never cleared.
* Production login returned 500 when the cache table was missing. A migration now creates it, and rate limiting fails open with logging.
* Event timestamps were taken before acquiring the lock (found by the concurrency test).

## 3. Load test: `tools/loadtest.py`

10 team clients + 1 host + 1 projector, each polling about once per second, for 120 s. The host
drives all 26 questions (open → teams submit → close → reveal → next). Target: local gunicorn,
3 workers × 4 threads, PostgreSQL 16.

```
duration 120.0s · 26 questions played and revealed · 1789 requests · 14.9 req/s
endpoint          count  errors   p50 ms   p95 ms   max ms
host action          89       0     19.2     37.2     44.8
host poll           120       0     24.3     40.2     51.3
projector poll      120       0     11.2     26.5     37.2
team poll          1200       0     12.5     23.4     36.7
team submit         260       0     15.3     27.5     49.3
error rate: 0.00%
database: 16028 transactions (133.6/s, 8.96 per request) · 1342060 rows read · 1464 rows written
score integrity: OK — every team's score matches the answer key
```

Interpretation: the expected classroom load (about 12–15 requests/s) uses a small fraction of one
machine. The p95 latency is under 41 ms on every endpoint, with zero errors, and every score is
correct under concurrent polling and submissions. Database transactions are about one per query
(Django autocommit); this is fine at this scale. These numbers are from a local container, so
**re-run the same script against the deployed Heroku app** before the presentation to include real
network latency.

## 4. Not tested here (limitations)

* **Real phones and Safari/iOS.** Only Chromium with mobile emulation was available in this
  container. The code avoids non-Safari APIs (`<dialog>` needs iOS 15.4+), but test on a real
  iPhone and a Samsung device during rehearsal.
* **The real projector and classroom Wi-Fi.**
* **The production deployment** (Heroku, DNS, TLS). Nothing was deployed.
* Fonts: the container has no Arial Black / Arial Narrow, so the screenshots use fallback fonts.
  A Mac has both, so the real projector will match the deck's typography more closely.
