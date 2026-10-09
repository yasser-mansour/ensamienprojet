"""
Simulated classroom load test: 10 team phones + 1 host dashboard + 1 projector, each polling
about once per second, while the host drives real questions and the teams submit answers.

    python tools/loadtest.py --base http://127.0.0.1:8001 --email host@example.com --password ... \
        [--duration 60] [--database-url postgres://...]

Reports error rate, latency percentiles per endpoint, request rate and (when --database-url
points at PostgreSQL) the number of database transactions/rows read during the run. It also
checks correctness under concurrency: every team's final score must equal what the answer key
says it earned.
"""

import argparse
import json
import random
import re
import statistics
import threading
import time
from collections import defaultdict

import requests

lock = threading.Lock()
latencies = defaultdict(list)
errors = defaultdict(int)
stop = threading.Event()


def record(name, started, ok):
    with lock:
        latencies[name].append((time.perf_counter() - started) * 1000)
        if not ok:
            errors[name] += 1


def csrf(session, base):
    return session.cookies.get("csrftoken") or session.get(base + "/").cookies.get("csrftoken")


class Team(threading.Thread):
    def __init__(self, base, code, name):
        super().__init__(daemon=True)
        self.base, self.name = base, name
        self.http = requests.Session()
        self.http.get(base + "/")
        r = self.http.post(base + "/", data={"code": code, "csrfmiddlewaretoken": csrf(self.http, base)}, allow_redirects=False)
        assert r.status_code == 302, f"code rejected for {name}: {r.status_code}"
        r = self.http.post(base + "/join/team/", data={"team_name": name, "csrfmiddlewaretoken": csrf(self.http, base)}, allow_redirects=False)
        assert r.status_code == 302 and "ensamien_team" in self.http.cookies, f"join failed for {name}"
        self.version = None
        self.state = None
        self.answered = set()
        self.plan = {}  # runtime_id -> answer to send (decided by the driver)

    def run(self):
        time.sleep(random.random())
        while not stop.is_set():
            t0 = time.perf_counter()
            try:
                r = self.http.get(self.base + "/api/live/state/" + (f"?v={self.version}" if self.version else ""), timeout=5)
                ok = r.status_code == 200
                data = r.json() if ok else {}
            except requests.RequestException:
                ok, data = False, {}
            record("team poll", t0, ok)
            if data.get("changed"):
                self.state = data["state"]
                self.version = self.state["version"]
            state = self.state
            q = state and state.get("question")
            if q and state["phase"] == "QUESTION_OPEN" and q["runtime_id"] not in self.answered and not state.get("my_submission"):
                answer = self.plan.get(q["runtime_id"])
                if answer is not None:
                    self.submit(q["runtime_id"], answer)
            time.sleep(max(0, 1.0 - (time.perf_counter() - t0)))

    def submit(self, runtime_id, answer):
        t0 = time.perf_counter()
        try:
            r = self.http.post(
                self.base + "/api/live/submit/",
                data=json.dumps({"runtime_id": runtime_id, "answer": answer}),
                headers={"Content-Type": "application/json", "X-CSRFToken": csrf(self.http, self.base)},
                timeout=5,
            )
            ok = r.status_code in (200, 201)
        except requests.RequestException:
            ok = False
        record("team submit", t0, ok)
        if ok:
            self.answered.add(runtime_id)


class Poller(threading.Thread):
    def __init__(self, name, http, url_fn):
        super().__init__(daemon=True)
        self.name_, self.http, self.url_fn = name, http, url_fn
        self.last = None

    def run(self):
        while not stop.is_set():
            t0 = time.perf_counter()
            try:
                r = self.http.get(self.url_fn(self), timeout=5)
                ok = r.status_code == 200
                if ok:
                    data = r.json()
                    if self.name_ == "projector poll" and data.get("changed"):
                        self.last = data["state"]["etag"]
                    elif self.name_ == "host poll":
                        self.last = data["state"]
            except requests.RequestException:
                ok = False
            record(self.name_, t0, ok)
            time.sleep(max(0, 1.0 - (time.perf_counter() - t0)))


def db_counters(url):
    if not url:
        return None
    import psycopg

    with psycopg.connect(url) as conn:
        row = conn.execute(
            "SELECT xact_commit + xact_rollback, tup_returned + tup_fetched, tup_inserted + tup_updated + tup_deleted "
            "FROM pg_stat_database WHERE datname = current_database()"
        ).fetchone()
    return {"transactions": row[0], "rows_read": row[1], "rows_written": row[2]}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--base", default="http://127.0.0.1:8001")
    p.add_argument("--email", required=True)
    p.add_argument("--password", required=True)
    p.add_argument("--duration", type=int, default=60)
    p.add_argument("--teams", type=int, default=10)
    p.add_argument("--database-url", default="")
    a = p.parse_args()
    base = a.base.rstrip("/")

    host = requests.Session()
    host.get(base + "/host/login/")
    r = host.post(base + "/host/login/", data={"email": a.email, "password": a.password, "csrfmiddlewaretoken": host.cookies["csrftoken"]}, allow_redirects=False)
    assert r.status_code == 302, "host login failed"
    r = host.post(base + "/host/sessions/new/", data={"csrfmiddlewaretoken": host.cookies["csrftoken"]}, allow_redirects=False)
    session_id = int(r.headers["Location"].rstrip("/").split("/")[-1])
    page = host.get(base + r.headers["Location"]).text
    code = re.search(r'stat__value--code">(\d{6})<', page).group(1)
    r = host.post(base + f"/host/sessions/{session_id}/display/", data={"csrfmiddlewaretoken": host.cookies["csrftoken"]}, allow_redirects=False)
    token = r.headers["Location"].rstrip("/").split("/")[-1]
    print(f"session {session_id} code {code}")

    teams = [Team(base, code, f"LOAD {i + 1:02d}") for i in range(a.teams)]
    print(f"{len(teams)} teams joined")
    host_poller = Poller("host poll", host, lambda s: base + f"/api/host/sessions/{session_id}/state/")
    proj = requests.Session()
    proj_poller = Poller("projector poll", proj, lambda s: base + f"/api/display/{token}/state/" + (f"?etag={s.last}" if s.last else ""))

    before = db_counters(a.database_url)
    started = time.time()
    for t in teams + [host_poller, proj_poller]:
        t.start()

    def action(name):
        st = host.get(base + f"/api/host/sessions/{session_id}/state/").json()["state"]
        t0 = time.perf_counter()
        r = host.post(
            base + f"/api/host/sessions/{session_id}/action/",
            data=json.dumps({"action": name, "expected_status": st["status"], "expected_runtime": st["current_runtime_id"], "request_id": f"{name}-{time.time()}"}),
            headers={"Content-Type": "application/json", "X-CSRFToken": host.cookies["csrftoken"]},
        )
        record("host action", t0, r.status_code == 200)
        return host.get(base + f"/api/host/sessions/{session_id}/state/").json()["state"]

    expected = {t.name: 0 for t in teams}
    questions = 0
    st = action("start_game")
    st = action("start_question")
    while time.time() - started < a.duration and st["status"] == "QUESTION_OPEN":
        q = st["question"]
        for i, t in enumerate(teams):
            correct = (i + questions) % 3 != 0
            key = q["answer_key"]
            if q["kind"] == "MATCH":
                ans = {"pairs": dict(key)}
                if not correct:
                    ks = list(key)
                    ans["pairs"][ks[0]], ans["pairs"][ks[1]] = key[ks[1]], key[ks[0]]
            elif q["kind"] == "ORDER":
                ans = {"order": list(key) if correct else list(reversed(key))}
            else:
                ans = {"option": key if correct else next(o["key"] for o in q["options"] if o["key"] != key)}
            t.plan[q["runtime_id"]] = ans
            if correct:
                expected[t.name] += q["points"]
        deadline = time.time() + 8
        while time.time() < deadline:
            if host.get(base + f"/api/host/sessions/{session_id}/state/").json()["state"]["submissions"]["count"] == len(teams):
                break
            time.sleep(0.25)
        action("close_question")
        action("reveal_answer")
        questions += 1
        time.sleep(1.0)
        st = action("next_question")
        if st["status"] == "MISSION_COMPLETE":
            if "next_mission" not in st["allowed_actions"]:
                st = action("finish_game")  # final mission played: show the final results
                break
            st = action("next_mission")
            st = action("start_question")
    if st["status"] == "QUESTION_OPEN":
        action("close_question")  # leave last question unscored and unrevealed
    remaining = a.duration - (time.time() - started)
    if remaining > 0:
        time.sleep(remaining)
    stop.set()
    elapsed = time.time() - started
    time.sleep(1.2)
    after = db_counters(a.database_url)

    final = {r["name"]: r["score"] for r in host.get(base + f"/api/host/sessions/{session_id}/state/").json()["state"]["leaderboard"]}
    total = sum(len(v) for v in latencies.values())
    total_err = sum(errors.values())
    print(f"\nduration {elapsed:.1f}s · {questions} questions played and revealed · {total} requests · {total / elapsed:.1f} req/s")
    print(f"{'endpoint':<16}{'count':>7}{'errors':>8}{'p50 ms':>9}{'p95 ms':>9}{'max ms':>9}")
    for name in sorted(latencies):
        vals = sorted(latencies[name])
        p95 = vals[min(len(vals) - 1, int(len(vals) * 0.95))]
        print(f"{name:<16}{len(vals):>7}{errors[name]:>8}{statistics.median(vals):>9.1f}{p95:>9.1f}{max(vals):>9.1f}")
    print(f"error rate: {100 * total_err / max(total, 1):.2f}%")
    if before and after:
        d = {k: after[k] - before[k] for k in before}
        print(
            f"database: {d['transactions']} transactions ({d['transactions'] / elapsed:.1f}/s, "
            f"{d['transactions'] / max(total, 1):.2f} per request) · {d['rows_read']} rows read · {d['rows_written']} rows written"
        )
    mismatches = {n: (final.get(n), e) for n, e in expected.items() if final.get(n) != e}
    print("score integrity:", "OK — every team's score matches the answer key" if not mismatches else f"MISMATCH {mismatches}")
    return 1 if mismatches or total_err else 0


if __name__ == "__main__":
    raise SystemExit(main())
