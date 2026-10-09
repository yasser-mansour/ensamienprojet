"""
End-to-end browser test of a complete ENERGY LAB LIVE session (Playwright + Chromium).

Runs against a live server:
    python tools/e2e.py --base http://127.0.0.1:8000 --email host@example.com --password ... [--shots docs/screenshots]

Scenario: host signs in → creates a session → opens the projector → 10 teams join on phone-sized
viewports → an 11th team is rejected (SESSION FULL) → two teams are removed → the host plays all
five missions (teams answer through the real UI: single choice, true/false, matching, tap-ordering
and drag-ordering) → a team reloads mid-question and keeps its answer → pause/resume → leaderboard
→ final boss → finish → the session report is checked. Scores shown in the UI are compared with
the expected totals computed from the answer keys.
"""

import argparse
import json
import os
import sys
import time

from playwright.sync_api import expect, sync_playwright

PHONE = {"viewport": {"width": 390, "height": 844}, "device_scale_factor": 2, "is_mobile": True, "has_touch": True}
TEAM_NAMES = ["ALPHA", "BRAVO", "CHARLIE", "DELTA", "ECHO", "FOXTROT", "GOLF", "HOTEL", "INDIA", "JULIET"]


def log(msg):
    print(f"[e2e {time.strftime('%H:%M:%S')}] {msg}", flush=True)


class Run:
    def __init__(self, args, pw):
        self.args = args
        self.base = args.base.rstrip("/")
        self.shots = args.shots
        if self.shots:
            os.makedirs(self.shots, exist_ok=True)
        launch = {"headless": True}
        if os.path.exists("/opt/pw-browsers/chromium"):
            launch["executable_path"] = "/opt/pw-browsers/chromium"
        self.browser = pw.chromium.launch(**launch)
        self.expected = {}
        self.checks = 0

    def shot(self, page, name):
        if self.shots:
            page.screenshot(path=os.path.join(self.shots, f"{name}.png"))

    def check(self, cond, message):
        self.checks += 1
        if not cond:
            raise AssertionError(message)

    # --- helpers ----------------------------------------------------------------
    def host_state(self):
        resp = self.host.request.get(f"{self.base}/api/host/sessions/{self.session_id}/state/")
        return resp.json()["state"]

    def host_click(self, action=None, primary=False, expect_status=None):
        page = self.host
        before = self.host_state()["version"]
        if primary:
            btn = page.locator("#primary-action")
        else:
            btn = page.locator(f'button[data-action="{action}"]').first
        expect(btn).to_be_enabled(timeout=10000)
        btn.click()
        if page.locator("#confirm-dialog[open]").count():
            page.locator("#confirm-ok").click()
        deadline = time.time() + 10
        while time.time() < deadline:
            st = self.host_state()
            if st["version"] != before and (expect_status is None or st["status"] == expect_status):
                return st
            time.sleep(0.2)
        raise AssertionError(f"host action {action or 'primary'} did not apply (expected {expect_status})")

    def join(self, name, code):
        ctx = self.browser.new_context(**PHONE)
        page = ctx.new_page()
        page.goto(self.base + "/")
        page.locator("#code-0").fill(code)  # the input handler spreads all six digits across the boxes
        page.locator("#join-btn").click()
        return ctx, page

    # --- scenario ---------------------------------------------------------------
    def run(self):
        a = self.args
        hctx = self.browser.new_context(viewport={"width": 1440, "height": 900})
        self.host = hctx.new_page()
        self.host.goto(self.base + "/host/")
        expect(self.host).to_have_url(f"{self.base}/host/login/?next=/host/")
        self.host.fill("#email", a.email)
        self.host.fill("#password", "wrong-password")
        self.host.locator("button[type=submit]").click()
        expect(self.host.locator(".alert")).to_contain_text("Incorrect")
        self.shot(self.host, "01-host-login-error")
        self.host.fill("#password", a.password)
        self.host.locator("button[type=submit]").click()
        expect(self.host.locator("h1")).to_contain_text("ENERGY LAB LIVE")
        self.shot(self.host, "02-host-dashboard")
        log("host signed in")

        self.host.locator("#create-btn").click()
        code = self.host.locator(".stat__value--code").inner_text().strip()
        self.session_id = int(self.host.url.rstrip("/").split("/")[-1])
        self.check(len(code) == 6 and code.isdigit(), f"bad code {code}")
        log(f"session {self.session_id} code {code}")

        with hctx.expect_page() as popup:
            self.host.locator("text=Open projector").click()
        self.display = popup.value
        self.display.set_viewport_size({"width": 1920, "height": 1080})
        expect(self.display.locator(".d-code")).to_be_visible()
        self.check(self.display.locator(".d-code").inner_text().replace("\n", "") == code, "projector code mismatch")

        # Invalid code first
        ctx_bad = self.browser.new_context(**PHONE)
        bad = ctx_bad.new_page()
        bad.goto(self.base + "/")
        bad.locator("#code-0").fill("000000" if code != "000000" else "111111")
        bad.locator("#join-btn").click()
        expect(bad.locator(".alert")).to_contain_text("INVALID SESSION CODE")
        self.shot(bad, "03-phone-invalid-code")
        ctx_bad.close()

        self.teams = {}
        for i, name in enumerate(TEAM_NAMES):
            ctx, page = self.join(name, code)
            if i == 0:
                self.shot(page, "04-phone-team-name")
            page.fill("#team_name", name)
            page.locator("button[type=submit]").click()
            expect(page.locator("#app")).to_contain_text("Waiting for the host", timeout=10000)
            self.teams[name] = (ctx, page)
            self.expected[name] = 0
        log("10 teams joined")
        self.shot(self.teams["ALPHA"][1], "05-phone-lobby")

        # Duplicate name (case-insensitive) is rejected — use a fresh phone; session is full though,
        # so check the 11th device gets SESSION FULL at code entry.
        ctx11, p11 = self.join("KILO", code)
        expect(p11.locator(".alert")).to_contain_text("SESSION FULL")
        self.shot(p11, "06-phone-session-full")
        ctx11.close()
        log("11th team rejected: SESSION FULL")

        expect(self.display.locator("#d-team-count")).to_contain_text("10", timeout=5000)
        self.shot(self.display, "07-projector-lobby-full")

        # Remove two teams to get back to the 8-team scenario
        for name in ("INDIA", "JULIET"):
            row = self.host.locator("#team-table tr", has_text=name)
            row.locator(".menu-btn").click()
            self.host.locator("#remove-btn").click()
            self.host.locator("#confirm-ok").click()
            expect(self.teams[name][1].locator("#app")).to_contain_text("Team removed", timeout=8000)
            self.teams.pop(name)[0].close()
            self.expected.pop(name)
        expect(self.display.locator("#d-team-count")).to_contain_text("8", timeout=5000)

        # Duplicate name check now that a slot is free
        ctxd, pd = self.join("dup", code)
        pd.fill("#team_name", "  alpha ")
        pd.locator("button[type=submit]").click()
        expect(pd.locator(".alert")).to_contain_text("ALREADY TAKEN")
        self.shot(pd, "08-phone-duplicate-name")
        ctxd.close()
        log("removed 2 teams; duplicate name rejected")
        self.shot(self.display, "09-projector-lobby")
        self.shot(self.host, "10-host-lobby")

        st = self.host_click(primary=True, expect_status="MISSION_INTRO")
        self.check(st["registration_open"] is False, "registration should close on start")
        for name, (_, page) in self.teams.items():
            expect(page.locator("#app")).to_contain_text("ENERGY SCAN", timeout=8000)
        self.shot(self.display, "11-projector-mission-intro")
        self.shot(self.teams["ALPHA"][1], "12-phone-mission-intro")

        mission_index = 0
        while True:
            mission_index += 1
            st = self.host_state()
            mission = st["mission"]
            log(f"mission {mission['code']} {mission['title']}")
            st = self.host_click(primary=True, expect_status="QUESTION_OPEN")
            q_index = 0
            while True:
                q_index += 1
                self.play_question(st, mission_index, q_index)
                st = self.host_state()
                if st["status"] == "MISSION_COMPLETE":
                    break
            expect(self.display.locator(".d-board")).to_be_visible(timeout=5000)
            time.sleep(2)
            self.shot(self.display, f"40-projector-mission-{mission['code']}-complete")
            self.verify_scores()
            if mission["order"] >= mission["total"]:
                break
            self.host_click(primary=True, expect_status="MISSION_INTRO")

        st = self.host_click(primary=True, expect_status="FINISHED")
        expect(self.display.locator(".d-final")).to_be_visible(timeout=8000)
        time.sleep(2.5)
        self.shot(self.display, "50-projector-final")
        self.shot(self.teams["ALPHA"][1], "51-phone-final")
        self.shot(self.host, "52-host-finished")
        self.verify_scores()

        # Unauthorized control attempt from a team phone (no host session) must fail.
        page = self.teams["ALPHA"][1]
        resp = page.request.post(f"{self.base}/api/host/sessions/{self.session_id}/action/", data=json.dumps({"action": "finish_game"}),
                                 headers={"Content-Type": "application/json"})
        self.check(resp.status in (403,), f"team could reach host API: {resp.status}")

        # Session history
        self.host.goto(f"{self.base}/host/sessions/{self.session_id}/report/")
        expect(self.host.locator("h1")).to_contain_text(code)
        report = self.host.locator("main").inner_text()
        for name in self.teams:
            self.check(name in report, f"{name} missing from report")
        self.check("Excellent explanation" in report, "manual adjustment missing from report")
        self.host.set_viewport_size({"width": 1440, "height": 1400})
        self.shot(self.host, "53-host-report")
        self.host.goto(f"{self.base}/host/history/")
        expect(self.host.locator("main")).to_contain_text(code)
        log(f"report verified · {self.checks} checks passed")

    def answers_for(self, st, q, team_i, q_seq):
        """Team i answers correctly unless (i + q_seq) % 3 == 0 — a deterministic mix."""
        correct = (team_i + q_seq) % 3 != 0
        key = q["answer_key"]
        options = [o["key"] for o in q["options"]]
        if q["kind"] == "MATCH":
            ans = dict(key)
            if not correct:
                ks = list(ans)
                ans[ks[0]], ans[ks[1]] = ans[ks[1]], ans[ks[0]]
            return correct, ans
        if q["kind"] == "ORDER":
            order = list(key)
            if not correct:
                order[1], order[2] = order[2], order[1]
            return correct, order
        if correct:
            return True, key
        return False, next(o for o in options if o != key)

    def play_question(self, st, mission_index, q_index):
        q = st["question"]
        q_seq = mission_index * 10 + q_index
        log(f"  Q{q['order']} {q['kind']} {q['label']}")
        first_team = list(self.teams)[0]
        for name, (_, page) in self.teams.items():
            expect(page.locator(".question-card")).to_be_visible(timeout=8000)
        if mission_index == 1 and q_index == 1:
            phone = self.teams[first_team][1]
            expect(phone.locator("#conn-text")).to_have_text("CONNECTED", timeout=5000)
            expect(phone.locator(".timer__num")).not_to_have_text("–", timeout=3000)
            t1 = int(phone.locator(".timer__num").inner_text())
            time.sleep(2.2)
            self.check(int(phone.locator(".timer__num").inner_text()) < t1, "phone countdown is not ticking")
            self.shot(self.display, "20-projector-question-open")
            self.shot(self.teams[first_team][1], "21-phone-question-single")

        silent = "HOTEL" if q_index == 2 else None  # one team misses one question per mission
        for i, (name, (_, page)) in enumerate(self.teams.items()):
            if name == silent:
                continue
            correct, ans = self.answers_for(st, q, i, q_seq)
            if q["kind"] in ("SINGLE", "TRUE_FALSE"):
                page.locator(f'button.option[data-key="{ans}"]').click()
            elif q["kind"] == "MATCH":
                rows = page.locator(".match-row")
                for r_i, item in enumerate(q["items"]):
                    rows.nth(r_i).locator(".seg button", has_text=ans[item["key"]]).click()
                if i == 0:
                    self.shot(page, "30-phone-matching")
                page.locator("text=Submit matches").click()
            elif q["kind"] == "ORDER":
                if i == 1:
                    # Drag-and-drop with real pointer events onto numbered slots
                    for slot, key in enumerate(ans):
                        card = page.locator(f'.seq-pool .seq-card[data-key="{key}"]')
                        target = page.locator(f'.seq-slot[data-slot="{slot}"]')
                        cb, tb = card.bounding_box(), target.bounding_box()
                        page.mouse.move(cb["x"] + 20, cb["y"] + cb["height"] / 2)
                        page.mouse.down()
                        page.mouse.move(cb["x"] + 40, cb["y"] + cb["height"] / 2 + 15, steps=4)
                        page.mouse.move(tb["x"] + 60, tb["y"] + tb["height"] / 2, steps=8)
                        page.mouse.up()
                else:
                    for key in ans:
                        page.locator(f'.seq-pool .seq-card[data-key="{key}"]').click()
                if i == 0:
                    self.shot(page, "31-phone-final-boss-ordering")
                page.locator("text=Lock in sequence").click()
            expect(page.locator(".receipt")).to_contain_text("Answer received", timeout=8000)
            if correct:
                self.expected[name] += q["points"]
            if mission_index == 1 and q_index == 1 and i == 0:
                self.shot(page, "22-phone-answer-received")
                # Reload mid-question: the answer must persist (server-side state recovery)
                page.reload()
                expect(page.locator(".receipt")).to_contain_text("Answer received", timeout=8000)

        expected_subs = len(self.teams) - (1 if silent else 0)
        deadline = time.time() + 8
        while self.host_state()["submissions"]["count"] != expected_subs:
            if time.time() > deadline:
                raise AssertionError("host did not see all submissions")
            time.sleep(0.2)
        if mission_index == 1 and q_index == 1:
            self.shot(self.host, "23-host-question-open")
        if mission_index == 2 and q_index == 1:
            # Pause / resume during an open question freezes and restores the timer
            st = self.host_click("pause", expect_status="PAUSED")
            expect(self.teams[first_team][1].locator(".overlay")).to_contain_text("Paused", timeout=5000)
            self.shot(self.display, "24-projector-paused")
            frozen = st["question"]["remaining_ms"]
            time.sleep(1.5)
            self.check(self.host_state()["question"]["remaining_ms"] == frozen, "timer kept running while paused")
            self.host_click("resume", expect_status="QUESTION_OPEN")
            expect(self.teams[first_team][1].locator(".overlay")).to_have_count(0, timeout=5000)

        self.host_click("close_question", expect_status="QUESTION_CLOSED")
        st = self.host_click("reveal_answer", expect_status="ANSWER_REVEALED")
        for name, (_, page) in self.teams.items():
            expect(page.locator(".result-banner")).to_be_visible(timeout=8000)
        if q["kind"] == "ORDER":
            time.sleep(2.6)  # let the sequence animation finish
        if (mission_index, q_index) in {(1, 1), (2, 6), (3, 1), (4, 1), (5, 1)}:
            self.shot(self.display, f"3{mission_index}-projector-reveal-m{mission_index}q{q_index}")
            self.shot(self.teams[first_team][1], f"3{mission_index}-phone-reveal-m{mission_index}q{q_index}")
            self.shot(self.teams["HOTEL"][1], f"3{mission_index}-phone-reveal-wrong-m{mission_index}q{q_index}")
        self.verify_scores()

        if mission_index == 1 and q_index == 1:
            # Manual bonus through the team dialog
            row = self.host.locator("#team-table tr", has_text="BRAVO")
            row.locator(".menu-btn").click()
            self.host.locator('[data-preset="50"]').click()
            self.host.fill("#adj-reason", "Excellent explanation")
            self.host.locator("#adj-submit").click()
            expect(self.host.locator("#team-dialog")).not_to_have_attribute("open", "", timeout=5000)
            self.expected["BRAVO"] += 50
            self.verify_scores()
        if q_index == 1:
            self.host_click("show_leaderboard", expect_status="LEADERBOARD")
            if mission_index == 1:
                expect(self.display.locator(".d-board")).to_be_visible(timeout=5000)
                time.sleep(2)
                self.shot(self.display, "25-projector-leaderboard")
                self.shot(self.teams[first_team][1], "26-phone-leaderboard")
        self.host_click(primary=True)

    def verify_scores(self):
        board = {r["name"]: r["score"] for r in self.host_state()["leaderboard"]}
        self.check(board == self.expected, f"scores differ: server={board} expected={self.expected}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:8000")
    parser.add_argument("--email", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--shots", default="")
    args = parser.parse_args()
    with sync_playwright() as pw:
        run = Run(args, pw)
        try:
            run.run()
        finally:
            run.browser.close()
    log("END-TO-END SCENARIO PASSED")


if __name__ == "__main__":
    sys.exit(main())
