/* ENSAMien shared client core: DOM helper, API client, server clock, poller, countdown, toasts. */

/** Build DOM nodes without innerHTML, so user-provided text is always rendered as text. */
export function h(tag, attrs, ...children) {
  const el = document.createElement(tag);
  if (attrs) {
    for (const [key, value] of Object.entries(attrs)) {
      if (value === null || value === undefined || value === false) continue;
      if (key === "class") el.className = value;
      else if (key === "dataset") Object.assign(el.dataset, value);
      else if (key === "style" && typeof value === "object") Object.assign(el.style, value);
      else if (key.startsWith("on") && typeof value === "function") el.addEventListener(key.slice(2), value);
      else if (value === true) el.setAttribute(key, "");
      else el.setAttribute(key, String(value));
    }
  }
  appendChildren(el, children);
  return el;
}

function appendChildren(el, children) {
  for (const child of children) {
    if (child === null || child === undefined || child === false) continue;
    if (Array.isArray(child)) appendChildren(el, child);
    else el.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
}

export function mount(container, ...nodes) {
  container.replaceChildren(...nodes.flat().filter(Boolean));
}

export function getCookie(name) {
  const match = document.cookie.split("; ").find((row) => row.startsWith(name + "="));
  return match ? decodeURIComponent(match.split("=")[1]) : "";
}

export class ApiError extends Error {
  constructor(code, message, status, data) {
    super(message);
    this.code = code;
    this.status = status;
    this.data = data;
  }
}

/** JSON request with CSRF, timeout and normalised errors. Always rejects with ApiError. */
export async function api(url, { method = "GET", body, timeout = 8000, signal } = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeout);
  if (signal) signal.addEventListener("abort", () => controller.abort(), { once: true });
  const headers = { Accept: "application/json" };
  if (method !== "GET") {
    headers["Content-Type"] = "application/json";
    headers["X-CSRFToken"] = getCookie("csrftoken");
  }
  let response;
  try {
    response = await fetch(url, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      credentials: "same-origin",
      cache: "no-store",
      signal: controller.signal,
    });
  } catch (err) {
    throw new ApiError("NETWORK", "CONNECTION PROBLEM — RETRYING", 0);
  } finally {
    clearTimeout(timer);
  }
  let data = null;
  try {
    data = await response.json();
  } catch {
    /* non-JSON error page */
  }
  if (!response.ok || !data || data.ok === false) {
    const error = (data && data.error) || {};
    const message =
      error.message || (response.status === 403 ? "NOT ALLOWED — PLEASE RELOAD" : `SERVER ERROR (${response.status})`);
    throw new ApiError(error.code || "HTTP_" + response.status, message, response.status, data);
  }
  return data;
}

/** Estimates the offset between this device's clock and the server's, from polling round-trips. */
export class ServerClock {
  constructor() {
    this.offset = 0;
    this.bestRtt = Infinity;
    this.samples = 0;
  }
  sample(serverTime, sentAt, receivedAt) {
    if (!serverTime) return;
    const rtt = receivedAt - sentAt;
    // Prefer low-latency samples; slowly forget old ones so drift is corrected.
    this.bestRtt = Math.min(this.bestRtt * 1.05 + 5, Infinity);
    if (rtt <= this.bestRtt || this.samples < 3) {
      this.bestRtt = rtt;
      this.offset = serverTime - (sentAt + rtt / 2);
    }
    this.samples += 1;
  }
  now() {
    return Date.now() + this.offset;
  }
}

/**
 * Short HTTP polling with: one request in flight at a time, randomised start offset,
 * request timeouts, exponential backoff with jitter during outages, faster resume when the
 * page becomes visible again, and clean shutdown when the page is left.
 */
export class Poller {
  constructor({ url, interval = 1000, timeout = 6000, maxBackoff = 15000, onData, onStatus, onFatal, clock }) {
    this.url = url; // function returning the URL for the next poll
    this.interval = interval;
    this.timeout = timeout;
    this.maxBackoff = maxBackoff;
    this.onData = onData;
    this.onStatus = onStatus || (() => {});
    this.onFatal = onFatal || (() => {});
    this.clock = clock;
    this.failures = 0;
    this.timer = null;
    this.inFlight = false;
    this.stopped = true;
    this.controller = null;
    this.online = null; // unknown until the first response, so the first status is always reported
    this._onVisibility = () => {
      if (document.visibilityState === "visible") this.poke();
    };
    this._onStop = () => this.stop();
  }

  start() {
    if (!this.stopped) return;
    this.stopped = false;
    document.addEventListener("visibilitychange", this._onVisibility);
    window.addEventListener("pagehide", this._onStop);
    window.addEventListener("online", this._onVisibility);
    this._schedule(Math.random() * 400); // spread clients so they don't poll in lockstep
  }

  stop() {
    this.stopped = true;
    clearTimeout(this.timer);
    if (this.controller) this.controller.abort();
    document.removeEventListener("visibilitychange", this._onVisibility);
    window.removeEventListener("pagehide", this._onStop);
    window.removeEventListener("online", this._onVisibility);
  }

  /** Poll as soon as possible (e.g. right after an action). */
  poke() {
    if (this.stopped) return;
    if (this.inFlight) {
      this.pokeAfter = true;
      return;
    }
    this._schedule(0);
  }

  _schedule(delay) {
    clearTimeout(this.timer);
    this.timer = setTimeout(() => this._tick(), delay);
  }

  _nextDelay() {
    if (this.failures === 0) {
      const hidden = document.visibilityState === "hidden";
      return (hidden ? this.interval * 3 : this.interval) + Math.random() * 150;
    }
    const backoff = Math.min(this.maxBackoff, this.interval * 2 ** Math.min(this.failures, 5));
    return backoff * (0.75 + Math.random() * 0.5);
  }

  _setOnline(value) {
    if (this.online !== value) {
      this.online = value;
      this.onStatus(value ? "online" : "offline", this.failures);
    } else if (!value) {
      this.onStatus("offline", this.failures);
    }
  }

  async _tick() {
    if (this.stopped || this.inFlight) return;
    this.inFlight = true;
    this.pokeAfter = false;
    this.controller = new AbortController();
    const sentAt = Date.now();
    try {
      const data = await api(this.url(), { timeout: this.timeout, signal: this.controller.signal });
      if (this.clock) this.clock.sample(data.server_time || (data.state && data.state.server_time), sentAt, Date.now());
      this.failures = 0;
      this._setOnline(true);
      this.onData(data);
    } catch (err) {
      if (err.status === 401 || err.status === 403 || err.status === 404) {
        this.stopped = true;
        this.onFatal(err);
        return;
      }
      this.failures += 1;
      if (this.failures >= 2) this._setOnline(false);
    } finally {
      this.inFlight = false;
      this.controller = null;
    }
    if (!this.stopped) this._schedule(this.pokeAfter ? 0 : this._nextDelay());
  }
}

/** Renders a countdown bound to a server deadline. Call update(question) on each state change. */
export class Countdown {
  constructor(root, clock, { lowAt = 5000 } = {}) {
    this.root = root;
    this.clock = clock;
    this.lowAt = lowAt;
    this.fill = root.querySelector(".timer__fill");
    this.num = root.querySelector(".timer__num");
    this.question = null;
    this.raf = null;
    this.onZero = null;
  }
  update(question) {
    this.question = question;
    this._loop();
  }
  remaining() {
    const q = this.question;
    if (!q) return 0;
    if (q.deadline === null || q.deadline === undefined) return q.remaining_ms || 0;
    return Math.max(0, q.deadline - this.clock.now());
  }
  _loop() {
    clearTimeout(this.raf);
    const q = this.question;
    if (!q) return;
    if (!this.root.isConnected) {
      // Not mounted yet (created during a render): retry briefly. Once detached for good, stop.
      if (!this.wasConnected && (this.waits = (this.waits || 0) + 1) < 100) this.raf = setTimeout(() => this._loop(), 30);
      return;
    }
    this.wasConnected = true;
    const remaining = this.remaining();
    const total = Math.max(q.duration_ms, remaining, 1);
    const paused = q.deadline === null || q.deadline === undefined;
    if (this.fill) this.fill.style.transform = `scaleX(${remaining / total})`;
    if (this.num) this.num.textContent = Math.ceil(remaining / 1000);
    this.root.classList.toggle("is-low", remaining <= this.lowAt && remaining > 0 && !paused);
    this.root.classList.toggle("is-paused", paused);
    this.root.classList.toggle("is-zero", remaining === 0);
    if (remaining === 0 && this.onZero && this._firedFor !== q.runtime_id) {
      this._firedFor = q.runtime_id;
      this.onZero();
    }
    if (!paused && remaining > 0) this.raf = setTimeout(() => this._loop(), 200);
  }
  stop() {
    clearTimeout(this.raf);
  }
}

export function timerEl(extraClass = "") {
  return h(
    "div",
    { class: `timer ${extraClass}`, role: "timer", "aria-live": "off" },
    h("div", { class: "timer__bar" }, h("div", { class: "timer__fill" })),
    h("div", { class: "timer__num" }, "–")
  );
}

let toastStack = null;
export function toast(message, kind = "info", ms = 3200) {
  if (!toastStack) {
    toastStack = h("div", { class: "toast-stack", role: "status", "aria-live": "polite" });
    document.body.append(toastStack);
  }
  const node = h("div", { class: `toast toast--${kind}` }, message);
  toastStack.append(node);
  setTimeout(() => node.remove(), ms);
}

export function markSvg() {
  const ns = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(ns, "svg");
  svg.setAttribute("viewBox", "0 0 32 32");
  svg.setAttribute("class", "mark");
  svg.setAttribute("aria-hidden", "true");
  svg.innerHTML =
    '<circle cx="16" cy="16" r="15" fill="#0E1116" stroke="#FFB400" stroke-width="2"/>' +
    '<path d="M16 16V2A14 14 0 0 1 30 16Z" fill="#FFB400"/><path d="M16 16V30A14 14 0 0 1 2 16Z" fill="#FFB400"/>';
  return svg;
}

export function requestId() {
  if (window.crypto && crypto.randomUUID) return crypto.randomUUID();
  return Date.now().toString(36) + Math.random().toString(36).slice(2);
}

export function readJsonScript(id) {
  const node = document.getElementById(id);
  return node ? JSON.parse(node.textContent) : null;
}
