/* Team (captain's phone) application. Polls /api/live/state/ and renders the current phase. */

import { api, ApiError, Countdown, h, mount, Poller, ServerClock, timerEl, toast } from "./core.js";

const script = document.getElementById("play-script");
const STATE_URL = script.dataset.stateUrl;
const SUBMIT_URL = script.dataset.submitUrl;
const HOME_URL = script.dataset.homeUrl;

const app = document.getElementById("app");
const scoreEl = document.getElementById("team-score");
const nameEl = document.getElementById("team-name");
const missionTag = document.getElementById("mission-tag");
const connDot = document.getElementById("conn-dot");
const connText = document.getElementById("conn-text");

const clock = new ServerClock();
let state = null;
let version = null;
let viewKey = "";
let countdown = null;
let sending = false;
let pauseOverlay = null;
const drafts = loadDrafts(); // in-progress MATCH / ORDER answers, keyed by runtime id

function loadDrafts() {
  try {
    return JSON.parse(sessionStorage.getItem("ensamien-drafts") || "{}");
  } catch {
    return {};
  }
}
function saveDrafts() {
  try {
    sessionStorage.setItem("ensamien-drafts", JSON.stringify(drafts));
  } catch {
    /* storage unavailable (private mode) — drafts just won't survive a reload */
  }
}

// --- polling ----------------------------------------------------------------

const poller = new Poller({
  url: () => STATE_URL + (version !== null ? `?v=${version}` : ""),
  interval: 1000,
  clock,
  onData(data) {
    if (data.changed) {
      state = data.state;
      version = state.version;
      render();
    }
  },
  onStatus(status) {
    const online = status === "online";
    connDot.className = "dot " + (online ? "dot--on" : "dot--off");
    connText.textContent = online ? "CONNECTED" : "RECONNECTING…";
  },
  onFatal(err) {
    if (err.status === 401) window.location.href = HOME_URL;
    else showFatal(err.message);
  },
});
poller.start();

function showFatal(message) {
  mount(app, h("div", { class: "stage stage__center" }, h("h2", null, "Connection lost"), h("p", { class: "muted" }, message),
    h("button", { class: "btn btn--primary", onclick: () => window.location.reload() }, "Reload")));
}

// --- render dispatch -------------------------------------------------------

function computeKey(s) {
  const q = s.question;
  const timeUp = q && q.status === "OPEN" && countdownRemaining(q) === 0;
  return JSON.stringify([
    s.phase,
    s.team && s.team.removed,
    s.mission && s.mission.code,
    q && q.runtime_id,
    q && q.status,
    !!s.my_submission,
    !!s.reveal,
    timeUp,
    ["LEADERBOARD", "MISSION_COMPLETE", "FINISHED", "ARCHIVED"].includes(s.phase) ? s.leaderboard : null,
  ]);
}

function countdownRemaining(q) {
  if (q.deadline === null || q.deadline === undefined) return q.remaining_ms || 1;
  return Math.max(0, q.deadline - clock.now());
}

function render(force = false) {
  if (!state) return;
  updateHeader();
  updatePause();
  const key = computeKey(state);
  if (!force && key === viewKey) {
    if (countdown && state.question) countdown.update(state.question);
    return;
  }
  viewKey = key;
  if (countdown) countdown.stop();
  countdown = null;

  if (state.team.removed) return mount(app, viewRemoved());
  switch (state.phase) {
    case "LOBBY":
    case "CREATED":
      return mount(app, viewLobby());
    case "MISSION_INTRO":
      return mount(app, viewIntro());
    case "QUESTION_OPEN":
    case "QUESTION_CLOSED":
      return mount(app, viewQuestion());
    case "ANSWER_REVEALED":
      return mount(app, viewReveal());
    case "LEADERBOARD":
      return mount(app, viewBoard("LEADERBOARD"));
    case "MISSION_COMPLETE":
      return mount(app, viewBoard("MISSION_COMPLETE"));
    case "FINISHED":
    case "ARCHIVED":
      return mount(app, viewFinished());
    default:
      return mount(app, viewLobby());
  }
}

function updateHeader() {
  nameEl.textContent = state.team.name;
  scoreEl.textContent = state.team.score !== undefined ? `${state.team.score} EP` : "";
  missionTag.textContent = state.mission ? `MISSION ${state.mission.code}` : "";
  document.title = `${state.team.name} · ENERGY LAB LIVE`;
}

function updatePause() {
  const paused = state.paused && !state.team.removed;
  if (paused && !pauseOverlay) {
    pauseOverlay = h("div", { class: "overlay", role: "alertdialog", "aria-label": "Game paused" },
      h("div", { class: "overlay__box" },
        h("span", { class: "eyebrow" }, "Mission control"),
        h("h2", null, "Paused"),
        h("p", { class: "muted narrow" }, "Stand by — the host will resume the game")));
    document.body.append(pauseOverlay);
  } else if (!paused && pauseOverlay) {
    pauseOverlay.remove();
    pauseOverlay = null;
  }
}

// --- views ------------------------------------------------------------------

function pulseIcon() {
  const ring = h("div", { class: "pulse-ring" });
  ring.innerHTML = '<svg viewBox="0 0 32 32" aria-hidden="true"><circle cx="16" cy="16" r="15" fill="#0E1116" stroke="#FFB400" stroke-width="2"/><path d="M16 16V2A14 14 0 0 1 30 16Z" fill="#FFB400"/><path d="M16 16V30A14 14 0 0 1 2 16Z" fill="#FFB400"/></svg>';
  return ring;
}

function viewLobby() {
  return h("section", { class: "stage stage__center" },
    h("span", { class: "eyebrow" }, "ENERGY LAB LIVE"),
    pulseIcon(),
    h("h1", { class: "stage__big" }, state.team.name),
    h("span", { class: "tag tag--ok" }, h("span", { class: "dot dot--on" }), "Connected"),
    h("div", { class: "panel corners", style: { padding: "18px", width: "100%" } },
      h("p", { class: "narrow", style: { margin: 0, fontSize: "20px", fontWeight: 700 } }, "Waiting for the host"),
      h("p", { class: "muted narrow", style: { margin: "6px 0 0", fontSize: "13px" } }, "Mission starting soon · keep this screen open")));
}

function viewIntro() {
  const m = state.mission;
  return h("section", { class: "stage" },
    h("span", { class: "eyebrow" }, `Mission ${m.code} / ${String(m.total).padStart(2, "0")}`),
    h("h1", { class: "stage__big" }, m.title),
    h("div", { class: "panel corners", style: { padding: "18px" } },
      h("p", { class: "narrow muted", style: { margin: "0 0 6px", fontSize: "12px" } }, "Objective"),
      h("p", { style: { margin: 0, fontSize: "18px", fontWeight: 700 } }, m.objective),
      m.briefing ? h("p", { class: "muted", style: { margin: "10px 0 0" } }, m.briefing) : null),
    h("div", { class: "status-strip" }, h("span", { class: "dot dot--wait" }), `${m.question_count} question${m.question_count === 1 ? "" : "s"} · get ready`));
}

function questionHeader(q) {
  const timer = timerEl();
  const compact = q.kind === "ORDER" || q.kind === "MATCH";
  const card = h("div", { class: `panel question-card corners ${compact ? "question-card--compact" : ""}` },
    h("div", { class: "question-card__label" },
      h("span", { class: "tag tag--amber" }, q.label || `Question ${q.order}`),
      h("span", { class: "tag" }, `${q.points} EP`)),
    q.context ? h("p", { class: "question-card__context" }, q.context) : null,
    h("div", { class: "question-card__prompt" }, q.prompt),
    h("div", { style: { marginTop: compact ? "10px" : "14px" } }, timer));
  countdown = new Countdown(timer, clock);
  countdown.onZero = () => {
    if (state && state.phase === "QUESTION_OPEN" && !state.my_submission) render(true);
  };
  if (q.status === "OPEN") countdown.update(q);
  else countdown.update({ ...q, deadline: null, remaining_ms: 0 });
  return card;
}

function viewQuestion() {
  const q = state.question;
  const open = state.phase === "QUESTION_OPEN" && q.status === "OPEN";
  const parts = [questionHeader(q)];
  if (state.my_submission) {
    parts.push(receipt(q, state.my_submission.answer, open ? "Waiting for other teams" : "Answers locked · waiting for the reveal"));
  } else if (!open) {
    parts.push(infoBox("Answers locked", "Your team did not answer in time · waiting for the reveal"));
  } else if (countdownRemaining(q) === 0) {
    parts.push(infoBox("Time is up", "Waiting for the host to close the question"));
  } else {
    parts.push(answerInput(q));
  }
  return h("section", { class: "stage" }, parts);
}

function infoBox(title, text) {
  return h("div", { class: "panel receipt" },
    h("div", { class: "receipt__head" }, title),
    h("div", { class: "muted narrow", style: { fontSize: "13px" } }, text));
}

function receipt(q, answer, text) {
  return h("div", { class: "panel receipt", role: "status" },
    h("div", { class: "status-strip" }, h("span", { class: "dot dot--on" }), "Answer received"),
    h("div", { class: "receipt__head" }, describeAnswer(q, answer)),
    h("div", { class: "muted narrow", style: { fontSize: "13px" } }, text));
}

function optionText(q, key) {
  const opt = q.options.find((o) => o.key === key);
  return opt ? opt.text : key;
}

function describeAnswer(q, answer) {
  if (!answer) return "—";
  if (answer.option) return `${answer.option} · ${optionText(q, answer.option)}`;
  if (answer.pairs) return Object.entries(answer.pairs).map(([k, v]) => `${k}→${v}`).join("  ");
  if (answer.order) return answer.order.join(" → ");
  return "";
}

function answerInput(q) {
  if (q.kind === "MATCH") return matchInput(q);
  if (q.kind === "ORDER") return orderInput(q);
  const tf = q.kind === "TRUE_FALSE";
  const buttons = q.options.map((o) =>
    h("button", {
      class: "option",
      type: "button",
      dataset: { key: o.key },
      onclick: (e) => submit(q, { option: o.key }, e.currentTarget),
    }, tf ? null : h("span", { class: "option__key" }, o.key), h("span", null, o.text)));
  return h("div", { class: `options ${tf ? "options--tf" : ""}`, role: "group", "aria-label": "Answers" }, buttons);
}

// --- MATCH ---------------------------------------------------------------

function matchInput(q) {
  const draft = (drafts[q.runtime_id] ||= { pairs: {} });
  const submitBtn = h("button", { class: "btn btn--primary btn--xl btn--block", type: "button" }, "Submit matches");
  const refresh = () => {
    submitBtn.disabled = q.items.some((item) => !draft.pairs[item.key]);
  };
  const rows = q.items.map((item) => {
    const seg = h("div", { class: "seg", role: "radiogroup", "aria-label": item.text },
      q.options.map((o) => {
        const btn = h("button", { type: "button", role: "radio", "aria-checked": String(draft.pairs[item.key] === o.key), class: draft.pairs[item.key] === o.key ? "is-on" : "" }, o.key);
        btn.addEventListener("click", () => {
          draft.pairs[item.key] = o.key;
          saveDrafts();
          seg.querySelectorAll("button").forEach((b) => {
            const on = b === btn;
            b.classList.toggle("is-on", on);
            b.setAttribute("aria-checked", String(on));
          });
          refresh();
        });
        return btn;
      }));
    return h("div", { class: "match-row" }, h("div", { class: "match-row__word" }, h("span", { class: "amber" }, item.key + "  "), item.text), seg);
  });
  submitBtn.addEventListener("click", () => submit(q, { pairs: { ...draft.pairs } }, submitBtn));
  refresh();
  return h("div", { class: "stage", style: { gap: "12px" } },
    h("div", { class: "match-defs" }, q.options.map((o) => h("div", { class: "match-def" }, h("b", null, o.key), h("span", null, o.text)))),
    rows,
    submitBtn);
}

// --- ORDER (Final Boss) ------------------------------------------------------

function orderInput(q) {
  const n = q.options.length;
  const draft = (drafts[q.runtime_id] ||= { slots: Array(n).fill(null) });
  const wrap = h("div", { class: "stage", style: { gap: "10px" } });
  const submitBtn = h("button", { class: "btn btn--primary btn--xl btn--block", type: "button" }, "Lock in sequence");
  submitBtn.addEventListener("click", () => submit(q, { order: [...draft.slots] }, submitBtn));

  const place = (key, index) => {
    const from = draft.slots.indexOf(key);
    if (index === undefined) index = draft.slots.indexOf(null);
    if (index < 0) return;
    if (from >= 0) draft.slots[from] = draft.slots[index]; // swap when moving between slots
    draft.slots[index] = key;
    saveDrafts();
    draw();
  };
  const unplace = (key) => {
    const i = draft.slots.indexOf(key);
    if (i >= 0) draft.slots[i] = null;
    saveDrafts();
    draw();
  };
  const move = (i, delta) => {
    const j = i + delta;
    if (j < 0 || j >= n) return;
    [draft.slots[i], draft.slots[j]] = [draft.slots[j], draft.slots[i]];
    saveDrafts();
    draw();
  };

  function card(key, inSlot, index) {
    const node = h("div", { class: "seq-card", dataset: { key }, tabindex: "0", role: "button",
      "aria-label": `${optionText(q, key)}${inSlot ? `, position ${index + 1}` : ", tap to place"}` },
      h("span", { class: "seq-card__key" }, key),
      h("span", null, optionText(q, key)),
      inSlot ? h("span", { class: "seq-card__tools" },
        h("button", { type: "button", "aria-label": "Move up", onclick: (e) => { e.stopPropagation(); move(index, -1); } }, "↑"),
        h("button", { type: "button", "aria-label": "Move down", onclick: (e) => { e.stopPropagation(); move(index, 1); } }, "↓"),
        h("button", { type: "button", "aria-label": "Remove", onclick: (e) => { e.stopPropagation(); unplace(key); } }, "✕")) : null);
    enableDrag(node, key, () => (inSlot ? null : place(key)), (slotIndex) => place(key, slotIndex));
    node.addEventListener("keydown", (e) => {
      if ((e.key === "Enter" || e.key === " ") && !inSlot) {
        e.preventDefault();
        place(key);
      }
    });
    return node;
  }

  function draw() {
    const pool = q.options.map((o) => o.key).filter((k) => !draft.slots.includes(k));
    mount(wrap,
      h("p", { class: "eyebrow", style: { margin: 0 } }, "Your sequence · tap cards in order or drag them"),
      h("div", { class: "seq-slots" }, draft.slots.map((key, i) =>
        h("div", { class: "seq-slot", dataset: { slot: String(i) } },
          h("span", { class: "seq-slot__num" }, i + 1),
          key ? card(key, true, i) : h("span", { class: "seq-slot__empty" }, i === draft.slots.indexOf(null) ? "Next card goes here" : "Empty")))),
      pool.length ? h("p", { class: "eyebrow", style: { margin: "2px 0 0" } }, "Event cards") : null,
      pool.length ? h("div", { class: "seq-pool" }, pool.map((k) => card(k, false))) : null,
      submitBtn);
    submitBtn.disabled = draft.slots.includes(null);
  }
  draw();
  return wrap;
}

/** Pointer-based drag (works for touch and mouse); a short tap without movement calls onTap. */
function enableDrag(node, key, onTap, onDrop) {
  node.addEventListener("pointerdown", (e) => {
    if (e.button !== 0 || e.target.closest("button")) return;
    const startX = e.clientX, startY = e.clientY;
    let ghost = null, target = null;
    node.setPointerCapture(e.pointerId);
    const onMove = (ev) => {
      if (!ghost && Math.hypot(ev.clientX - startX, ev.clientY - startY) > 8) {
        const rect = node.getBoundingClientRect();
        ghost = node.cloneNode(true);
        ghost.classList.add("seq-ghost");
        ghost.style.width = rect.width + "px";
        document.body.append(ghost);
        node.classList.add("is-dragging");
      }
      if (ghost) {
        ghost.style.left = ev.clientX - 30 + "px";
        ghost.style.top = ev.clientY - 24 + "px";
        ghost.hidden = true;
        const under = document.elementFromPoint(ev.clientX, ev.clientY);
        ghost.hidden = false;
        const slot = under && under.closest(".seq-slot");
        if (target && target !== slot) target.classList.remove("is-target");
        target = slot;
        if (target) target.classList.add("is-target");
      }
    };
    const onUp = () => {
      node.removeEventListener("pointermove", onMove);
      node.removeEventListener("pointerup", onUp);
      node.removeEventListener("pointercancel", onUp);
      if (ghost) {
        ghost.remove();
        node.classList.remove("is-dragging");
        if (target) {
          target.classList.remove("is-target");
          onDrop(Number(target.dataset.slot));
        }
      } else {
        onTap();
      }
    };
    node.addEventListener("pointermove", onMove);
    node.addEventListener("pointerup", onUp);
    node.addEventListener("pointercancel", onUp);
  });
}

// --- submission ---------------------------------------------------------------

async function submit(q, answer, sourceEl) {
  if (sending || state.my_submission) return;
  sending = true;
  const buttons = app.querySelectorAll("button, .seq-card");
  buttons.forEach((b) => (b.disabled = true));
  if (sourceEl) sourceEl.classList.add(sourceEl.classList.contains("option") ? "is-chosen" : "is-busy");
  const body = { runtime_id: q.runtime_id, answer };
  try {
    let data;
    for (let attempt = 0; ; attempt++) {
      try {
        data = await api(SUBMIT_URL, { method: "POST", body, timeout: 6000 });
        break;
      } catch (err) {
        // Network failures are retried with the same body: the server treats it idempotently.
        if (err.code !== "NETWORK" || attempt >= 3) throw err;
        await new Promise((r) => setTimeout(r, 600 * 2 ** attempt));
      }
    }
    state.my_submission = { answer: data.answer, submitted_at: data.submitted_at };
    delete drafts[q.runtime_id];
    saveDrafts();
    if (navigator.vibrate) navigator.vibrate(30);
    render(true);
  } catch (err) {
    toast(err instanceof ApiError ? err.message : "COULD NOT SEND ANSWER", "error");
    render(true);
  } finally {
    sending = false;
    poller.poke();
  }
}

// --- reveal & results ----------------------------------------------------------

function viewReveal() {
  const q = state.question;
  const r = state.reveal;
  const mine = state.my_submission && state.my_submission.answer;
  let banner;
  if (!mine) {
    banner = h("div", { class: "result-banner result-banner--none" }, h("h2", null, "No answer"), h("div", { class: "result-banner__pts muted" }, "+0 EP"));
  } else if (r.correct) {
    banner = h("div", { class: "result-banner result-banner--ok" }, h("h2", null, "Correct"), h("div", { class: "result-banner__pts" }, `+${r.points_awarded} EP`));
  } else {
    banner = h("div", { class: "result-banner result-banner--bad" }, h("h2", null, "Incorrect"), h("div", { class: "result-banner__pts" }, "+0 EP"));
  }
  return h("section", { class: "stage" },
    h("span", { class: "eyebrow" }, `${q.label || "Question " + q.order} · answer`),
    banner,
    correctAnswerView(q, r, mine),
    h("div", { class: "panel explain" },
      h("p", { style: { margin: 0 } }, r.explanation),
      r.clarification ? h("div", { class: "note" }, h("b", null, "Science note · supplementary"), r.clarification.replace(/^Science note \(supplementary\):\s*/i, "")) : null),
    h("div", { class: "status-strip" }, h("span", { class: "dot dot--wait" }), "Waiting for the host"));
}

function correctAnswerView(q, r, mine) {
  if (q.kind === "ORDER") {
    return h("div", { class: "seq-slots" }, r.answer_key.map((key, i) => {
      const ok = mine && mine.order && mine.order[i] === key;
      return h("div", { class: "seq-slot" }, h("span", { class: "seq-slot__num" }, i + 1),
        h("div", { class: `seq-card ${mine ? (ok ? "is-correct" : "is-wrong") : ""}` }, h("span", { class: "seq-card__key" }, key), h("span", null, optionText(q, key))));
    }));
  }
  if (q.kind === "MATCH") {
    return h("div", { class: "stage", style: { gap: "8px" } }, q.items.map((item) => {
      const correct = r.answer_key[item.key];
      const chosen = mine && mine.pairs && mine.pairs[item.key];
      return h("div", { class: "match-row" },
        h("div", { class: "match-row__word" }, item.text),
        h("div", { class: "muted", style: { fontSize: "14px" } }, h("b", { class: "amber" }, correct + " "), optionText(q, correct)),
        chosen && chosen !== correct ? h("div", { class: "tag tag--bad" }, `Your answer: ${chosen}`) : null);
    }));
  }
  return h("div", { class: `options ${q.kind === "TRUE_FALSE" ? "options--tf" : ""}` }, q.options.map((o) => {
    const isKey = o.key === r.answer_key;
    const isMine = mine && mine.option === o.key;
    const cls = ["option", isKey ? "is-correct" : isMine ? "is-wrong" : "is-faded"].join(" ");
    return h("button", { class: cls, type: "button", disabled: true },
      q.kind === "TRUE_FALSE" ? null : h("span", { class: "option__key" }, o.key),
      h("span", null, o.text, isMine ? h("span", { class: "dim narrow", style: { display: "block", fontSize: "12px" } }, "Your answer") : null));
  }));
}

function leaderList() {
  return h("ol", { class: "leader-list" }, (state.leaderboard || []).map((row) =>
    h("li", { class: `leader-row ${row.name === state.team.name ? "is-me" : ""}` },
      h("span", { class: "leader-row__rank" }, `#${row.rank}`),
      h("span", { class: "leader-row__name" }, row.name),
      h("span", { class: "leader-row__score" }, `${row.score} EP`))));
}

function viewBoard(kind) {
  const m = state.mission;
  const title = kind === "MISSION_COMPLETE" ? `Mission ${m ? m.code : ""} complete` : "Leaderboard";
  return h("section", { class: "stage" },
    h("span", { class: "eyebrow" }, kind === "MISSION_COMPLETE" ? m && m.title : "Current ranking"),
    h("h1", { class: "stage__big" }, title),
    h("div", { class: "panel corners", style: { padding: "18px", display: "flex", alignItems: "center", gap: "18px" } },
      h("div", { class: "big-rank" }, `#${state.team.rank || "–"}`),
      h("div", null,
        h("div", { class: "narrow muted", style: { fontSize: "12px" } }, `of ${state.team.team_count} teams`),
        h("div", { style: { fontFamily: "var(--font-mono)", fontSize: "26px", fontWeight: 700 } }, `${state.team.score} EP`))),
    leaderList());
}

function viewFinished() {
  const top = (state.leaderboard || [])[0];
  const won = top && state.team.rank === 1;
  return h("section", { class: "stage" },
    h("span", { class: "eyebrow" }, "Final crash simulation · complete"),
    h("h1", { class: "stage__big" }, won ? "Mission champions" : "Engineers certified"),
    h("div", { class: "panel corners", style: { padding: "18px", display: "flex", alignItems: "center", gap: "18px" } },
      h("div", { class: "big-rank" }, `#${state.team.rank || "–"}`),
      h("div", null,
        h("div", { class: "narrow muted", style: { fontSize: "12px" } }, "Final score"),
        h("div", { style: { fontFamily: "var(--font-mono)", fontSize: "26px", fontWeight: 700 } }, `${state.team.score} EP`))),
    leaderList(),
    h("p", { class: "muted", style: { textAlign: "center" } }, "Thank you, engineers."));
}

function viewRemoved() {
  return h("section", { class: "stage stage__center" },
    h("span", { class: "eyebrow" }, "Session"),
    h("h1", { class: "stage__big" }, "Team removed"),
    h("p", { class: "muted" }, "The host removed this team from the session. Ask the host if this was a mistake."),
    h("button", { class: "btn btn--primary btn--block", onclick: () => document.getElementById("leave-form").submit() }, "Back to start"));
}
