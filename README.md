# ENSAMien · ENERGY LAB LIVE

Interactive classroom platform for the **ENERGY LAB — CRASH TEST #05** presentation
(English for Engineering, Unit 5: Energy · ENSAM Meknès).

Up to **10 team phones** join a session with a six-digit code. The host controls everything
from a MacBook dashboard, while a separate **projector view** shows the code, QR, questions,
reveals and leaderboards. Five missions (26 questions) are taken from the Unit 5 textbook
pages and the team's own presentation deck.

Everything runs on Django with plain HTTP polling: no WebSockets, Redis or other real-time
infrastructure is needed.

```
Host (MacBook)      ──POST actions / GET state (1 s)──┐
Projector window    ──GET display state (1 s)─────────┤──  Django  ──  PostgreSQL
10 team phones      ──GET state (1 s) / POST answers──┘
```

## Quick start (local)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # then set DJANGO_DEBUG=1, DJANGO_SECURE_SSL=0, DATABASE_URL=sqlite:///db.sqlite3
python manage.py migrate      # also loads the five ENERGY LAB missions
python manage.py createcachetable
python manage.py create_host --email you@example.com   # prompts for a password (min. 10 chars)
python manage.py runserver 0.0.0.0:8000
```

* Host: <http://localhost:8000/host/login/>
* Teams: <http://localhost:8000/>. To test with real phones on the same Wi-Fi, use
  `http://<your-mac-ip>:8000/` and add that IP to `DJANGO_ALLOWED_HOSTS`.

PostgreSQL works the same way: set `DATABASE_URL=postgres://user:pass@localhost:5432/ensamien`.

## Running a session (presentation day)

1. Sign in at `/host/login/` → **CREATE NEW SESSION**. A random six-digit code is generated.
2. Click **OPEN PROJECTOR ↗**. This opens a separate window, so drag it to the projector screen and press **F** for full screen.
   The projector uses its own read-only link and never has host permissions.
3. Captains open the site (or scan the QR), enter the code and a team name. Teams appear live
   on the projector and in the dashboard's team panel.
4. **START GAME** closes registration and opens Mission 01. The big amber button always
   shows the next logical step (start question → close → reveal → next …).
5. Teams answer on their phones. The dashboard shows answers received and who has locked in.
   The timer never reveals anything on its own; you close and reveal when you choose.
6. After the last mission, **FINISH GAME** shows the winner. The full report stays under
   **Session history**.

Failsafes: pause/resume (freezes the timer), +15 s, reopen a closed question, skip a question,
restart a mission (points already won are never awarded twice), manual EP adjustments with a
reason, remove a team (reopens its slot), and a **recovery code** for a captain who lost their phone.
A captain who simply refreshes or loses Wi-Fi reconnects automatically.

## Tests

```bash
python manage.py test tests            # 110+ unit/integration tests (PostgreSQL also runs the threaded concurrency tests)
pip install -r requirements-dev.txt
python tools/e2e.py --email you@example.com --password '…' --shots docs/screenshots   # full browser scenario
python tools/loadtest.py --email you@example.com --password '…' --duration 60          # 10 teams + host + projector
```

## Documentation

* [`docs/TECHNICAL.md`](docs/TECHNICAL.md): architecture, state machine, polling protocol, data model, security.
* [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md): deploying to `ensamien.yassermansour.com` (Heroku).
* [`docs/CONTENT.md`](docs/CONTENT.md): where every mission question comes from, and source limitations.
* [`docs/REHEARSAL.md`](docs/REHEARSAL.md): checklist for the classroom rehearsal.
* [`docs/TEST_REPORT.md`](docs/TEST_REPORT.md): latest test, load-test and browser-test results.

## Project layout

```
config/      settings (env-driven), urls, wsgi
accounts/    host e-mail login, rate limiting, `create_host` command
games/       reusable content: Experience → Mission → Question → AnswerOption, JSON loader
live/        sessions, teams, state machine (engine.py), services, role-scoped serializers, APIs
templates/   team (mobile), host (dashboard), projector
static/      app.css design system; core.js (poller, clock, DOM), play.js, host.js, display.js
fixtures/    energy_lab.json: the five missions
tests/       automated test suite
tools/       e2e.py (Playwright), loadtest.py
docs/        technical, deployment, content, rehearsal, test report, screenshots
```
