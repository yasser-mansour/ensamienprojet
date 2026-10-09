/* Host mission-control dashboard. Polls the full host state and sends guarded actions. */

import { api, Countdown, h, mount, Poller, requestId, ServerClock, timerEl, toast } from "./core.js";

const script = document.getElementById("host-script");
const STATE_URL = script.dataset.stateUrl;
const ACTION_URL = script.dataset.actionUrl;
const LOGIN_URL = script.dataset.loginUrl;

const $ = (id) => document.getElementById(id);
const clock = new ServerClock();
let state = null;
let stageKey = "";
let countdown = null;
let busy = false;
let dialogTeamId = null;

const STATUS_LABEL = {
  CREATED: "Created",
  LOBBY: "Lobby",
  MISSION_INTRO: "Mission intro",
  QUESTION_OPEN: "Question open",
  QUESTION_CLOSED: "Question closed",
  ANSWER_REVEALED: "Answer revealed",
  LEADERBOARD: "Leaderboard",
  MISSION_COMPLETE: "Mission complete",
  PAUSED: "Paused",
  FINISHED: "Finished",
  ARCHIVED: "Archived",
};

const HINTS = {
  LOBBY: "Teams join with the code. Start when everyone is in — registration closes automatically.",
  MISSION_INTRO: "Projector shows the mission briefing. Start the first question when the class is ready.",
  QUESTION_OPEN: "Teams are answering. The timer reaching zero never reveals the answer — you stay in control.",
  QUESTION_CLOSED: "Answers are locked. Reveal to score and show the explanation.",
  ANSWER_REVEALED: "Points awarded. Explain, then continue or show the leaderboard.",
  LEADERBOARD: "Rankings on the projector.",
  MISSION_COMPLETE: "Mission finished. Continue to the next mission when ready.",
  PAUSED: "Everything is frozen, including the question timer.",
  FINISHED: "Final results on the projector. Session preserved in history.",
  ARCHIVED: "Archived — read only.",
};

const poller = new Poller({
  url: () => STATE_URL,
  interval: 1000,
  clock,
  onData(data) {
    state = data.state;
    render();
  },
  onStatus(status) {
    $("net-dot").className = "dot " + (status === "online" ? "dot--on" : "dot--off");
    $("net-text").textContent = status === "online" ? "LIVE" : "RECONNECTING";
  },
  onFatal(err) {
    if (err.status === 403) window.location.href = LOGIN_URL + "?next=" + encodeURIComponent(location.pathname);
    else toast(err.message, "error", 8000);
  },
});
poller.start();

// --- actions ---------------------------------------------------------------------

async function perform(action, params = {}, button = null) {
  if (busy || !state) return null;
  busy = true;
  setControlsBusy(true, button);
  const body = {
    action,
    params,
    request_id: requestId(),
    expected_status: state.status,
    expected_runtime: state.current_runtime_id,
  };
  try {
    let data;
    for (let attempt = 0; ; attempt++) {
      try {
        data = await api(ACTION_URL, { method: "POST", body, timeout: 8000 });
        break;
      } catch (err) {
        // Retrying with the same request_id is safe: the server applies each request at most once.
        if (err.code !== "NETWORK" || attempt >= 2) throw err;
        await new Promise((r) => setTimeout(r, 700 * (attempt + 1)));
      }
    }
    $("action-feedback").textContent = "✓ " + data.result.message;
    return data.result;
  } catch (err) {
    toast(err.message, err.code === "STALE" ? "info" : "error", 4500);
    $("action-feedback").textContent = "";
    return null;
  } finally {
    busy = false;
    setControlsBusy(false, button);
    poller.poke();
  }
}

function setControlsBusy(on, button) {
  document.querySelectorAll("[data-action], #primary-action, #reg-toggle").forEach((b) => {
    if (on) b.disabled = true;
  });
  if (button) button.classList.toggle("is-busy", on);
  if (!on && state) renderControls();
}

function confirmDialog(title, text, okLabel = "Confirm") {
  const dialog = $("confirm-dialog");
  $("confirm-title").textContent = title;
  $("confirm-text").textContent = text;
  $("confirm-ok").textContent = okLabel;
  return new Promise((resolve) => {
    dialog.addEventListener("close", () => resolve(dialog.returnValue === "ok"), { once: true });
    dialog.showModal();
  });
}

document.querySelectorAll("[data-action]").forEach((btn) => {
  btn.addEventListener("click", async () => {
    const message = btn.dataset.confirm;
    if (message && !(await confirmDialog(btn.textContent.trim(), message))) return;
    perform(btn.dataset.action, btn.dataset.params ? JSON.parse(btn.dataset.params) : {}, btn);
  });
});

$("reg-toggle").addEventListener("click", (e) => {
  perform(state.registration_open ? "close_registration" : "open_registration", {}, e.currentTarget);
});

$("primary-action").addEventListener("click", async (e) => {
  const spec = primarySpec();
  if (!spec || !spec.action) {
    if (spec && spec.href) window.open(spec.href, "_blank", "noopener");
    return;
  }
  if (spec.confirm && !(await confirmDialog(spec.label, spec.confirm))) return;
  perform(spec.action, {}, e.currentTarget);
});

function primarySpec() {
  if (!state) return null;
  const q = state.question;
  const lastQuestion = q && q.order >= (q.question_count || 0);
  const finalMission = state.mission && state.mission.order >= state.mission.total;
  switch (state.status) {
    case "LOBBY":
      return { action: "start_game", label: state.teams.length ? `Start game · ${state.teams.length} team${state.teams.length > 1 ? "s" : ""}` : "Waiting for teams…" };
    case "MISSION_INTRO":
      return { action: "start_question", label: `Start question 1 of ${state.mission.question_count}` };
    case "QUESTION_OPEN":
      return { action: "close_question", label: `Close question · ${state.submissions.count}/${state.submissions.total} answered` };
    case "QUESTION_CLOSED":
      return { action: "reveal_answer", label: "Reveal answer" };
    case "ANSWER_REVEALED":
    case "LEADERBOARD":
      return { action: "next_question", label: lastQuestion ? "Complete mission" : `Next question · ${q.order + 1} of ${q.question_count}` };
    case "MISSION_COMPLETE":
      return finalMission
        ? { action: "finish_game", label: "Finish game · final results", confirm: "Show the final results? No more questions can be opened afterwards." }
        : { action: "next_mission", label: "Next mission" };
    case "PAUSED":
      return { action: "resume", label: "Resume" };
    case "FINISHED":
    case "ARCHIVED":
      return { href: document.querySelector('a[href$="/report/"]').href, label: "Open session report ↗" };
    default:
      return null;
  }
}

// --- rendering ------------------------------------------------------------------

/** Re-render a panel only when its data changed, so buttons inside stay clickable between polls. */
const signatures = {};
function mountIfChanged(id, signature, build) {
  const sig = JSON.stringify(signature);
  if (signatures[id] === sig) return;
  signatures[id] = sig;
  mount($(id), build());
}

function seenLabel(seconds) {
  if (seconds < 60) return `${Math.max(10, Math.floor(seconds / 10) * 10)}s+`;
  return `${Math.floor(seconds / 60)} min`;
}

function render() {
  renderTop();
  renderMissions();
  renderStage();
  renderControls();
  renderTeams();
  renderBoard();
  renderLog();
}

function renderTop() {
  $("top-status").textContent = STATUS_LABEL[state.status] + (state.paused ? ` · ${STATUS_LABEL[state.phase]}` : "");
  const connected = state.teams.filter((t) => t.connected).length;
  $("top-teams").textContent = `${connected} / ${state.teams.length}`;
  $("top-mission").textContent = state.mission ? `${state.mission.code} · ${state.mission.title}` : "—";
  $("top-reg").textContent = state.registration_open ? "Open" : "Closed";
  $("top-reg").style.color = state.registration_open ? "var(--ok)" : "var(--muted)";
  document.title = `${STATUS_LABEL[state.status]} · ${state.code} · Mission control`;
}

function renderMissions() {
  mountIfChanged("missions", state.missions, () => state.missions.map((m) =>
    h("div", { class: `mstep ${m.current ? "is-current" : ""} ${m.done ? "is-done" : ""}` },
      h("div", { class: "mstep__code" }, m.done ? `✓ ${m.code}` : m.code),
      h("div", { class: "mstep__title" }, m.title))));
}

function renderStage() {
  const q = state.question;
  const key = JSON.stringify([state.status, state.phase, q && q.runtime_id, q && q.status, state.mission && state.mission.code, state.leaderboard.length]);
  $("phase-title").textContent = STATUS_LABEL[state.status];
  $("phase-hint").textContent = HINTS[state.status] || "";
  mount($("phase-tags"),
    state.paused ? h("span", { class: "tag tag--amber" }, `Paused during ${STATUS_LABEL[state.phase]}`) : null,
    q && ["QUESTION_OPEN", "QUESTION_CLOSED", "ANSWER_REVEALED", "LEADERBOARD"].includes(state.phase)
      ? h("span", { class: "tag" }, `Q ${q.order}/${q.question_count}${q.attempt > 1 ? ` · attempt ${q.attempt}` : ""}`) : null,
    state.speed_bonus_enabled ? h("span", { class: "tag tag--amber" }, "Speed bonus on") : null);

  // Submission gauge updates every poll; the question block only when something structural changes.
  renderGauge();
  if (key === stageKey) return;
  stageKey = key;
  mount($("stage-main"), stageMain());
}

function stageMain() {
  const phase = state.phase;
  const m = state.mission;
  if (phase === "LOBBY" || phase === "CREATED") {
    return h("div", null,
      h("p", { class: "eyebrow" }, "Lobby"),
      h("p", { class: "host-q__context" }, state.teams.length ? `${state.teams.length} team${state.teams.length > 1 ? "s" : ""} joined` : "Waiting for the first team"),
      h("p", { class: "muted" }, "Open the projector so the class can see the code and QR. Teams appear here and on the projector as they join."));
  }
  if (phase === "FINISHED" || phase === "ARCHIVED") {
    const top = state.leaderboard[0];
    return h("div", null,
      h("p", { class: "eyebrow" }, "Mission complete"),
      h("p", { class: "host-q__context" }, top ? `Winner: ${top.name} · ${top.score} EP` : "No teams"),
      h("p", { class: "muted" }, "All records are preserved in the session report."));
  }
  if (phase === "MISSION_INTRO" || (phase === "MISSION_COMPLETE" && m)) {
    return h("div", null,
      h("p", { class: "eyebrow" }, `Mission ${m.code} / ${String(m.total).padStart(2, "0")}${phase === "MISSION_COMPLETE" ? " · complete" : ""}`),
      h("p", { class: "host-q__context" }, m.title),
      h("p", { style: { margin: "4px 0", fontWeight: 700 } }, m.objective),
      h("p", { class: "muted", style: { margin: 0 } }, m.briefing),
      h("p", { class: "dim narrow", style: { fontSize: "12px", marginTop: "10px" } }, `${m.question_count} question(s) · default ${m.default_duration}s each`));
  }
  const q = state.question;
  if (!q) return h("div", { class: "empty" }, "No question");
  const keyText = (k) => (q.options.find((o) => o.key === k) || {}).text || k;
  let options;
  if (q.kind === "MATCH") {
    options = h("div", { class: "host-opts" },
      q.items.map((item) => h("div", { class: "host-opt is-key" }, h("b", null, item.key), h("span", null, `${item.text} → ${q.answer_key[item.key]} · ${keyText(q.answer_key[item.key])}`))));
  } else if (q.kind === "ORDER") {
    options = h("div", { class: "host-opts" },
      q.answer_key.map((k, i) => h("div", { class: "host-opt is-key" }, h("b", null, i + 1), h("span", null, `${k} · ${keyText(k)}`))));
  } else {
    options = h("div", { class: "host-opts" },
      q.options.map((o) => h("div", { class: `host-opt ${o.key === q.answer_key ? "is-key" : ""}` }, h("b", null, o.key), h("span", null, o.text))));
  }
  return h("div", null,
    h("div", { style: { display: "flex", gap: "6px", flexWrap: "wrap" } },
      h("span", { class: "tag tag--amber" }, q.label || `Question ${q.order}`),
      h("span", { class: "tag" }, `${q.source === "TEXTBOOK" ? "Textbook" : "Supplementary"} · ${q.source_reference}`),
      h("span", { class: "tag" }, `${q.points} EP`)),
    q.context ? h("p", { class: "host-q__context" }, q.context) : null,
    h("p", { class: "muted narrow", style: { margin: 0, fontSize: "14px" } }, q.prompt),
    h("p", { class: "stat__label", style: { margin: "14px 0 0", color: "var(--ok)" } }, "Answer key · host only until reveal"),
    options,
    h("p", { style: { margin: "12px 0 0", color: "var(--sand)", fontSize: "14px" } }, q.explanation),
    q.clarification ? h("div", { class: "note" }, h("b", null, "Science note"), q.clarification.replace(/^Science note \(supplementary\):\s*/i, "")) : null);
}

function renderGauge() {
  const gauge = $("stage-gauge");
  const q = state.question;
  const showQ = q && ["QUESTION_OPEN", "QUESTION_CLOSED", "ANSWER_REVEALED", "LEADERBOARD"].includes(state.phase);
  if (!showQ) {
    if (countdown) countdown.stop();
    countdown = null;
    mount(gauge,
      h("div", { class: "stat__label" }, "Teams joined"),
      h("div", { class: "gauge__big" }, state.teams.length, h("small", null, " / 10")));
    return;
  }
  if (!countdown || !gauge.querySelector(".timer") || gauge.dataset.runtime !== String(q.runtime_id)) {
    const timer = timerEl();
    gauge.dataset.runtime = q.runtime_id;
    mount(gauge,
      h("div", { class: "stat__label" }, "Time remaining"),
      timer,
      h("div", { class: "stat__label", style: { marginTop: "12px" } }, "Answers received"),
      h("div", { class: "gauge__big", id: "subs-big" }),
      h("div", { class: "dim narrow", style: { fontSize: "12px" }, id: "time-note" }));
    countdown = new Countdown(timer, clock);
  }
  const subs = state.submissions || { count: 0, total: 0 };
  mount($("subs-big"), String(subs.count), h("small", null, ` / ${subs.total}`));
  const qForTimer = state.phase === "QUESTION_OPEN" ? q : { ...q, deadline: null, remaining_ms: q.status === "OPEN" ? q.remaining_ms : 0 };
  countdown.update(qForTimer);
  const zero = state.phase === "QUESTION_OPEN" && q.deadline && q.deadline <= clock.now();
  $("time-note").textContent = zero ? "Time is up — close the question when ready" : state.status === "PAUSED" ? "Timer frozen" : "";
}

function renderControls() {
  const allowed = new Set(state.allowed_actions);
  document.querySelectorAll("[data-action]").forEach((b) => {
    b.disabled = busy || !allowed.has(b.dataset.action);
  });
  const reg = $("reg-toggle");
  reg.textContent = state.registration_open ? "Close registration" : "Open registration";
  reg.disabled = busy || !allowed.has(state.registration_open ? "close_registration" : "open_registration");
  $("speed-toggle").textContent = state.speed_bonus_enabled ? "Speed bonus: on" : "Speed bonus: off";
  const spec = primarySpec();
  const primary = $("primary-action");
  primary.textContent = spec ? spec.label : "—";
  primary.disabled = busy || !spec || (spec.action ? !allowed.has(spec.action) : false);
  const pause = document.querySelector('.controls__primary [data-action="pause"]');
  pause.disabled = busy || !allowed.has("pause");
}

function renderTeams() {
  $("team-count").textContent = `${state.team_table.length} / 10`;
  const revealed = state.question && state.question.status === "REVEALED";
  const inQuestion = state.question && ["QUESTION_OPEN", "QUESTION_CLOSED", "ANSWER_REVEALED", "LEADERBOARD"].includes(state.phase);
  const rows = state.team_table.map((t) => ({ ...t, last_seen_s: t.connected ? 0 : seenLabel(t.last_seen_s) }));
  mountIfChanged("team-table", [rows, revealed, inQuestion], () => teamTable(rows, revealed, inQuestion));
}

function teamTable(rows, revealed, inQuestion) {
  if (!rows.length) return h("div", { class: "empty" }, "No teams yet");
  return h("table", { class: "team-table" },
    h("thead", null, h("tr", null, h("th", null, "#"), h("th", null, "Team"), h("th", null, inQuestion ? "Answer" : ""), h("th", { style: { textAlign: "right" } }, "EP"), h("th", null))),
    h("tbody", null, rows.map((t) => {
      let answer = "";
      if (inQuestion) {
        if (revealed) answer = t.submitted ? (t.correct ? h("span", { class: "tag tag--ok" }, "✓") : h("span", { class: "tag tag--bad" }, "✗")) : h("span", { class: "dim" }, "—");
        else answer = t.submitted ? h("span", { class: "tag tag--amber" }, "Locked") : h("span", { class: "dim narrow", style: { fontSize: "12px" } }, "…");
      }
      return h("tr", null,
        h("td", { class: "dim mono" }, t.slot),
        h("td", null,
          h("div", { style: { display: "flex", alignItems: "center", gap: "6px" } },
            h("span", { class: `dot ${t.connected ? "dot--on" : "dot--off"}`, title: t.connected ? "Connected" : `Last seen ${t.last_seen_s}s ago` }),
            h("span", { class: "team-name" }, t.name)),
          h("div", { class: "team-sub" }, t.connected ? `#${t.rank}` : `offline · ${t.last_seen_s}`, t.recovery_pending ? " · recovery code active" : "", t.reconnects ? ` · moved ${t.reconnects}×` : "")),
        h("td", null, answer),
        h("td", { class: "num" }, t.score),
        h("td", null, h("button", { class: "menu-btn", type: "button", title: `Manage ${t.name}`, "aria-label": `Manage ${t.name}`, onclick: () => openTeamDialog(t) }, "⋯")));
    })));
}

function renderBoard() {
  mountIfChanged("leaderboard", state.leaderboard, () => state.leaderboard.length ? boardList() : h("div", { class: "empty" }, "Scores appear here"));
}

function boardList() {
  return (h("ol", { class: "leader-list" }, state.leaderboard.map((r) =>
    h("li", { class: "leader-row" }, h("span", { class: "leader-row__rank" }, `#${r.rank}`), h("span", { class: "leader-row__name" }, r.name), h("span", { class: "leader-row__score" }, r.score)))));
}

function renderLog() {
  const fmt = (ms) => new Date(ms).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  mountIfChanged("event-log", state.events, () => state.events.map((e) => h("div", { class: "log__row" }, h("span", { class: "log__time" }, fmt(e.time)), h("span", null, e.message))));
}

// --- team dialog ---------------------------------------------------------------------

function openTeamDialog(team) {
  dialogTeamId = team.id;
  $("team-dialog-title").textContent = `${team.name} · ${team.score} EP`;
  $("adj-points").value = "";
  $("adj-reason").value = "";
  $("recovery-out").hidden = true;
  const allowed = new Set(state.allowed_actions);
  $("adj-submit").disabled = !allowed.has("adjust_score");
  $("recovery-btn").disabled = !allowed.has("issue_recovery");
  $("remove-btn").disabled = !allowed.has("remove_team");
  $("team-dialog").showModal();
}

document.querySelectorAll("[data-preset]").forEach((b) =>
  b.addEventListener("click", () => {
    $("adj-points").value = b.dataset.preset;
    $("adj-reason").focus();
  })
);

$("adj-submit").addEventListener("click", async (e) => {
  const points = parseInt($("adj-points").value, 10);
  const reason = $("adj-reason").value.trim();
  if (!points) return toast("Enter a non-zero number of points", "error");
  if (!reason) return toast("A reason is required", "error");
  const result = await perform("adjust_score", { team_id: dialogTeamId, points, reason }, e.currentTarget);
  if (result) {
    toast(result.message, "ok");
    $("team-dialog").close();
  }
});

$("recovery-btn").addEventListener("click", async (e) => {
  const result = await perform("issue_recovery", { team_id: dialogTeamId }, e.currentTarget);
  if (result) {
    $("recovery-code").textContent = result.recovery_code;
    $("recovery-out").hidden = false;
  }
});

$("remove-btn").addEventListener("click", async (e) => {
  $("team-dialog").close();
  const ok = await confirmDialog("Remove team", "The team keeps its history but leaves the game, and its slot is reopened. Their phone will show “Team removed”.", "Remove team");
  if (!ok) return;
  const result = await perform("remove_team", { team_id: dialogTeamId }, e.currentTarget);
  if (result) toast(result.message, "ok");
});
