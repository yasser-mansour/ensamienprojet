/* Projector display. Read-only: polls display-safe state with a scoped token. */

import { Countdown, h, mount, Poller, ServerClock, timerEl } from "./core.js";

const script = document.getElementById("display-script");
const STATE_URL = script.dataset.stateUrl;
const JOIN_HOST = script.dataset.joinHost;
const stage = document.getElementById("stage");
const clock = new ServerClock();

let state = null;
let etag = null;
let sceneKey = "";
let countdown = null;
const seenTeams = new Set();

const poller = new Poller({
  url: () => STATE_URL + (etag ? `?etag=${encodeURIComponent(etag)}` : ""),
  interval: 1000,
  clock,
  onData(data) {
    if (data.changed) {
      state = data.state;
      etag = state.etag;
      render();
    }
  },
  onStatus(status) {
    document.getElementById("d-offline").hidden = status === "online";
  },
  onFatal(err) {
    mount(stage, h("div", { class: "d-intro" }, h("p", { class: "d-eyebrow" }, "Display link"), h("h1", { class: "d-big" }, "Link expired"),
      h("p", { class: "d-intro__obj" }, "Reopen the projector from mission control.")));
  },
});
poller.start();

// --- chrome -------------------------------------------------------------------------

const fsBtn = document.getElementById("fs-btn");
function toggleFullscreen() {
  if (document.fullscreenElement) document.exitFullscreen();
  else document.documentElement.requestFullscreen && document.documentElement.requestFullscreen().catch(() => {});
}
fsBtn.addEventListener("click", toggleFullscreen);
document.addEventListener("keydown", (e) => {
  if (e.key === "f" || e.key === "F") toggleFullscreen();
});
let idle;
document.addEventListener("mousemove", () => {
  document.body.classList.remove("hide-cursor");
  clearTimeout(idle);
  idle = setTimeout(() => document.body.classList.add("hide-cursor"), 2500);
});

// --- render -------------------------------------------------------------------------

const BOARD_PHASES = ["LEADERBOARD", "MISSION_COMPLETE", "FINISHED", "ARCHIVED"];

function render() {
  renderChrome();
  const q = state.question;
  const key = JSON.stringify([
    state.phase,
    state.mission && state.mission.code,
    q && q.runtime_id,
    q && q.status,
    !!state.reveal,
    BOARD_PHASES.includes(state.phase) ? state.leaderboard : null,
  ]);
  if (key !== sceneKey) {
    sceneKey = key;
    if (countdown) countdown.stop();
    countdown = null;
    mount(stage, scene());
  }
  updateLive();
  renderPause();
}

function renderChrome() {
  const m = state.mission;
  document.getElementById("d-top-mission").textContent = m ? `MISSION ${m.code} · ${m.title}` : "";
  const prog = document.getElementById("d-progress");
  const total = m ? m.total : 5;
  mount(prog, Array.from({ length: total }, (_, i) =>
    h("span", { class: m && i + 1 < m.order ? "is-done" : m && i + 1 === m.order ? "is-current" : "" })));
  if (["FINISHED", "ARCHIVED"].includes(state.phase)) prog.querySelectorAll("span").forEach((s) => (s.className = "is-done"));
}

function scene() {
  switch (state.phase) {
    case "LOBBY":
    case "CREATED":
      return lobbyScene();
    case "MISSION_INTRO":
      return introScene();
    case "QUESTION_OPEN":
    case "QUESTION_CLOSED":
      return questionScene();
    case "ANSWER_REVEALED":
      return revealScene();
    case "LEADERBOARD":
      return boardScene("CURRENT RANKING", "LEADERBOARD");
    case "MISSION_COMPLETE":
      return boardScene(state.mission ? state.mission.title : "", `MISSION ${state.mission ? state.mission.code : ""} COMPLETE`);
    case "FINISHED":
    case "ARCHIVED":
      return finalScene();
    default:
      return lobbyScene();
  }
}

/** Parts of the scene that change without a scene switch (teams joining, answer counts, timer). */
function updateLive() {
  const grid = document.getElementById("d-team-grid");
  if (grid) {
    mount(grid, Array.from({ length: state.max_teams }, (_, i) => {
      const t = state.teams[i];
      if (!t) return h("div", { class: "d-team d-team--empty" }, "OPEN SLOT");
      const isNew = !seenTeams.has(t.name);
      seenTeams.add(t.name);
      return h("div", { class: `d-team ${t.connected ? "" : "is-off"}`, style: isNew ? null : { animation: "none" } },
        h("div", { style: { minWidth: 0 } },
          h("div", { class: "d-team__name" }, t.name),
          h("div", { class: "d-team__st" }, t.connected ? "● CONNECTED" : "○ OFFLINE")));
    }));
    document.getElementById("d-team-count").replaceChildren(h("b", null, String(state.teams.length)), ` / ${state.max_teams} TEAMS`);
  }
  const subs = document.getElementById("d-subs");
  if (subs && state.submissions) {
    mount(subs, `${state.submissions.count} / ${state.submissions.total}`, h("small", null, "ANSWERS LOCKED"));
  }
  if (countdown && state.question) {
    const q = state.question;
    countdown.update(state.phase === "QUESTION_OPEN" && q.status === "OPEN" ? q : { ...q, deadline: null, remaining_ms: q.status === "OPEN" ? q.remaining_ms : 0 });
  }
}

function renderPause() {
  let overlay = document.getElementById("d-pause");
  if (state.paused && !overlay) {
    overlay = h("div", { class: "d-pause", id: "d-pause" },
      h("div", { style: { textAlign: "center" } }, h("p", { class: "d-eyebrow" }, "Mission control"), h("h2", null, "PAUSED"),
        h("p", { class: "d-intro__obj", style: { margin: "1vw auto 0" } }, "Stand by")));
    stage.append(overlay);
  } else if (!state.paused && overlay) {
    overlay.remove();
  }
}

// --- scenes -------------------------------------------------------------------------

function lobbyScene() {
  const qr = document.getElementById("qr-tpl").content.cloneNode(true);
  return h("section", { class: "d-scene d-lobby" },
    h("div", null,
      h("p", { class: "d-eyebrow" }, "ENERGY LAB LIVE · CRASH TEST #05"),
      h("h1", { class: "d-huge", style: { marginTop: "1vw" } }, "JOIN THE", h("br"), h("span", { class: "amber" }, "MISSION")),
      h("p", { class: "d-join__url" }, JOIN_HOST),
      h("p", { class: "d-join__label" }, "ENTER CODE"),
      h("div", { class: "d-code", "aria-label": `Session code ${state.code}` }, [...state.code].map((d) => h("span", null, d))),
      state.registration_open ? null : h("p", { class: "tag tag--bad", style: { fontSize: "1vw", marginTop: "1.4vw" } }, "REGISTRATION CLOSED")),
    h("div", { class: "d-qr" }, h("div", null, qr), h("p", { class: "d-qr__cap" }, "SCAN TO OPEN THE SITE · THEN ENTER THE CODE")),
    h("div", { class: "d-teams" },
      h("div", { class: "d-teams__head" },
        h("span", { class: "d-eyebrow" }, "CONNECTED TEAMS"),
        h("span", { class: "d-teams__count", id: "d-team-count" })),
      h("div", { class: "d-team-grid", id: "d-team-grid" })));
}

function introScene() {
  const m = state.mission;
  return h("section", { class: "d-scene d-intro" },
    h("p", { class: "d-eyebrow" }, `MISSION ${m.code} / ${String(m.total).padStart(2, "0")}${m.is_final ? " · FINAL CHALLENGE" : ""}`),
    h("div", { class: "d-intro__code" }, m.code),
    h("h1", { class: "d-big" }, m.title),
    h("p", { class: "d-intro__obj" }, m.objective),
    m.briefing ? h("p", { class: "d-intro__obj", style: { fontSize: "1.5vw", color: "var(--muted)" } }, m.briefing) : null,
    h("div", { class: "d-intro__meta" },
      h("span", { class: "tag tag--amber" }, `${m.question_count} QUESTION${m.question_count === 1 ? "" : "S"}`),
      h("span", { class: "tag" }, "STAND BY FOR THE FIRST QUESTION")));
}

function qHead(q) {
  return h("div", null,
    h("div", { class: "d-q__head" },
      h("span", { class: "d-eyebrow" }, q.label || `QUESTION ${q.order}`),
      h("span", { style: { display: "flex", gap: "0.6vw" } },
        h("span", { class: "tag", style: { fontSize: "0.9vw" } }, q.source === "TEXTBOOK" ? "TEXTBOOK" : "SUPPLEMENTARY"),
        h("span", { class: "tag tag--amber", style: { fontSize: "0.9vw" } }, `+${q.points} EP`))),
    q.context ? h("p", { class: "d-q__context", style: { margin: "0.8vw 0 0" } }, q.context) : null,
    h("p", { class: "d-q__prompt" }, q.prompt));
}

function optionsGrid(q, reveal) {
  if (q.kind === "ORDER") {
    const order = reveal ? reveal.answer_key : q.options.map((o) => o.key);
    const text = (k) => q.options.find((o) => o.key === k).text;
    return h("div", { class: `d-seq ${reveal ? "d-seq--reveal" : ""}` }, order.map((k, i) =>
      h("div", { class: "d-seq__card", style: reveal ? { animationDelay: `${i * 0.55}s` } : null },
        h("span", { class: "d-seq__key" }, k),
        reveal ? h("span", { class: "d-seq__step" }, `STEP ${i + 1}`) : null,
        h("span", null, text(k)))));
  }
  if (q.kind === "MATCH") {
    return h("div", { class: "d-match" },
      h("div", { class: "d-match__words" }, q.items.map((item) =>
        h("div", { class: "d-match__word" }, h("b", null, item.key), item.text, reveal ? h("em", null, `→ ${reveal.answer_key[item.key]}`) : null))),
      h("div", { class: "d-options", style: { gridTemplateColumns: "1fr" } }, q.options.map((o) =>
        h("div", { class: `d-option ${reveal ? "is-correct" : ""}` }, h("span", { class: "d-option__key" }, o.key), h("span", null, o.text)))));
  }
  const cols = q.options.length === 3 ? "d-options--3" : "";
  return h("div", { class: `d-options ${cols}` }, q.options.map((o) => {
    const cls = reveal ? (o.key === reveal.answer_key ? "is-correct" : "is-faded") : "";
    return h("div", { class: `d-option ${cls}` }, q.kind === "TRUE_FALSE" ? null : h("span", { class: "d-option__key" }, o.key), h("span", null, o.text));
  }));
}

function questionScene() {
  const q = state.question;
  const closed = state.phase === "QUESTION_CLOSED" || q.status !== "OPEN";
  const timer = timerEl("d-timer");
  countdown = new Countdown(timer, clock, { lowAt: 5000 });
  return h("section", { class: "d-scene d-question" },
    qHead(q),
    optionsGrid(q, null),
    closed
      ? h("div", { class: "d-band" }, "ANSWERS LOCKED · AWAITING REVEAL", h("span", { id: "d-subs", style: { display: "none" } }))
      : h("div", { class: "d-bottom" }, timer, h("div", { class: "d-subs", id: "d-subs" })));
}

function revealScene() {
  const q = state.question;
  const r = state.reveal;
  const results = r.results || [];
  return h("section", { class: "d-scene d-question", style: { gridTemplateRows: "auto auto minmax(0, 1fr)" } },
    qHead(q),
    optionsGrid(q, r),
    h("div", { class: "d-reveal" },
      h("div", { class: "d-explain" },
        h("h3", null, `CORRECT ANSWER · ${r.answer_display}`),
        h("div", null, r.explanation),
        r.clarification ? h("div", { class: "note" }, h("b", null, "SCIENCE NOTE · SUPPLEMENTARY"), r.clarification.replace(/^Science note \(supplementary\):\s*/i, "")) : null),
      h("div", null,
        h("p", { class: "d-eyebrow" }, "RESULTS"),
        h("p", { class: "d-big", style: { fontSize: "3.6vw", margin: "0.4vw 0" } }, `${r.correct_count} / ${state.teams.length}`, h("span", { class: "muted", style: { fontSize: "1.4vw", fontFamily: "var(--font-narrow)", letterSpacing: "0.2em", marginLeft: "1vw" } }, "TEAMS CORRECT")),
        h("div", { class: "d-results" }, results.map((t) => h("span", { class: `tag ${t.correct ? "tag--ok" : "tag--bad"}` }, `${t.correct ? "✓" : "✗"} ${t.name}`))))));
}

function boardRows(rows) {
  const max = Math.max(1, ...rows.map((r) => r.score));
  return h("div", { class: "d-board" }, rows.map((r, i) =>
    h("div", { class: "d-board__row", style: { animationDelay: `${i * 0.08}s` } },
      h("span", { class: "d-board__rank" }, `#${r.rank}`),
      h("span", { class: "d-board__name" }, r.name),
      h("span", { class: "d-board__bar" }, h("i", { style: { width: `${(r.score / max) * 100}%`, animationDelay: `${0.2 + i * 0.08}s` } })),
      h("span", { class: "d-board__score" }, `${r.score} EP`))));
}

function boardScene(eyebrow, title) {
  const rows = state.leaderboard || [];
  return h("section", { class: "d-scene", style: { display: "grid", gridTemplateRows: "auto 1fr", gap: "1.6vw" } },
    h("div", { style: { textAlign: "center" } }, h("p", { class: "d-eyebrow" }, eyebrow), h("h1", { class: "d-big" }, title)),
    rows.length ? boardRows(rows) : h("p", { class: "d-intro__obj" }, "No teams"));
}

function finalScene() {
  const rows = state.leaderboard || [];
  const winners = rows.filter((r) => r.rank === 1);
  return h("section", { class: "d-scene d-final" },
    h("div", { class: "d-winner" },
      h("p", { class: "d-eyebrow" }, "FINAL CRASH SIMULATION · COMPLETE"),
      h("h1", { class: "d-big" }, "MISSION", h("br"), "COMPLETE"),
      h("p", { class: "d-eyebrow", style: { marginTop: "2vw", color: "var(--muted)" } }, winners.length > 1 ? "WINNING TEAMS" : "WINNING TEAM"),
      h("div", { class: "d-winner__name d-big" }, winners.map((w) => w.name).join(" · ") || "—"),
      winners.length ? h("div", { class: "d-winner__score" }, `${winners[0].score} EP`) : null,
      h("p", { class: "d-intro__obj", style: { marginTop: "1.4vw" } }, "ENGINEERS CERTIFIED. THANK YOU, ENGINEERS.")),
    boardRows(rows.slice(0, 10)));
}
