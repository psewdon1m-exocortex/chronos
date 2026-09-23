import { bindActionGeometry } from "./ui-interactions.js";
// Bounded history windows retain an independent cursor. Loading old events
// never pins the cursor to the first page or competes with live refresh.
function node(tag, text, className) {
  const element = document.createElement(tag);
  if (text !== undefined) element.textContent = String(text);
  if (className) element.className = className;
  return element;
}
function normalize(event) {
  const status = event.outcome || event.status || event.level || "info";
  const raw = String(status).toUpperCase().replaceAll("_", "-");
  const outcome = typeof status === "number" ? status === 304 ? "NOT-MODIFIED" : status >= 400 ? "ERROR" : status >= 200 && status < 300 ? "SUCCESS" : "UNKNOWN" : raw;
  const tone = /error|fail|denied|reject|critical/i.test(outcome) ? "error" : /^(success|successful|ok|completed)$/i.test(outcome) ? "success" : /warn/i.test(outcome) ? "warning" : "neutral";
  return {
    outcome, tone,
    id: event.id ?? event.event_id ?? event.sequence,
    cursor: event.sequence ?? event.id ?? event.event_id,
    timestamp: event.occurredAt ?? event.occurred_at ?? event.created_at ?? event.at ?? event.timestamp,
    body: [event.action || event.summary || event.message || event.event || "Event", (typeof event.target === "object" ? event.target?.id : event.target) || event.resourceId].filter(Boolean).join(" · "),
  };
}
function timestamp(value) {
  const date = new Date(typeof value === "number" ? value * 1000 : value);
  if (!Number.isFinite(date.getTime())) return "Time unavailable";
  const part = n => String(n).padStart(2, "0");
  return part(date.getDate()) + "." + part(date.getMonth() + 1) + "." + date.getFullYear() + " "
    + part(date.getHours()) + ":" + part(date.getMinutes()) + ":" + part(date.getSeconds());
}
export function mountServiceLogs(root, options) {
  root.classList.add("exo-service-logs");
  const stopGeometry = bindActionGeometry(root);
  let records = [], cursor, more = true, busy = false, closed = false, history = false, failure = "", loaded = false, autoLoading = false;
  const controllers = new Set();
  const actions = node("div", undefined, "exo-log-actions");
  const download = node("a", "Download archived logs", "exo-log-download"); download.href = options.download || "#"; if (options.onDownload) download.onclick = event => { event.preventDefault(); options.onDownload(); }; download.setAttribute("download", "");
  const refresh = node("button", "Refresh newest"), older = node("button", "Load older events");
  refresh.type = older.type = "button";
  const status = node("p"); status.setAttribute("role", "status");
  const error = node("p", "", "exo-agent-error"); error.setAttribute("role", "alert");
  const viewport = node("div", undefined, "exo-log-viewport"); viewport.tabIndex = 0; viewport.setAttribute("aria-label", "Service log history");
  const header = node("div", undefined, "exo-log-row exo-log-header");
  for (const label of ["TYPE", "BODY", "TIME"]) header.append(node("span", label));
  const footer = node("div", undefined, "exo-log-footer"); footer.append(older, refresh);
  actions.append(status, download); root.replaceChildren(actions, error, viewport, footer);
  const commandBand = root.closest(".logs-content")?.querySelector(".logs-command-band");
  if (commandBand) commandBand.append(download);
  const rows = new Map();
  function anchor() {
    const top = viewport.getBoundingClientRect().top + header.getBoundingClientRect().height;
    const row = [...viewport.querySelectorAll("[data-event-id]")].find(item => item.getBoundingClientRect().bottom > top);
    return { id: row?.dataset.eventId, offset: row ? row.getBoundingClientRect().top - viewport.getBoundingClientRect().top : 0, scroll: viewport.scrollTop };
  }
  function render(saved = anchor()) {
    if (closed) return;
    if (header.parentNode !== viewport) viewport.prepend(header);
    const retained = new Set(records.map(item => String(item.id)));
    for (const [id, row] of rows) if (!retained.has(id)) { row.remove(); rows.delete(id); }
    viewport.querySelector(".exo-log-empty")?.remove();
    if (!records.length) viewport.append(node("p", !loaded ? "Loading events…" : "No retained events.", "exo-log-empty"));
    let previous = header;
    for (const record of records) {
      const id = String(record.id);
      let row = rows.get(id);
      if (!row) {
        row = node("div", undefined, "exo-log-row"); row.dataset.eventId = id;
        row.append(node("strong"), node("span"), node("time")); rows.set(id, row);
      }
      if (row.children[0].textContent !== record.outcome) row.children[0].textContent = record.outcome; row.children[0].className = "exo-log-" + record.tone;
      if (row.children[1].textContent !== record.body) row.children[1].textContent = record.body;
      if (row.children[2].textContent !== timestamp(record.timestamp)) row.children[2].textContent = timestamp(record.timestamp); row.children[2].title = "Local browser time";
      if (previous.nextElementSibling !== row) previous.after(row);
      previous = row;
    }
    const target = rows.get(saved.id);
    if (saved.scroll === 0) viewport.scrollTop = 0;
    else if (target) viewport.scrollTop += target.getBoundingClientRect().top - viewport.getBoundingClientRect().top - saved.offset;
    else viewport.scrollTop = saved.scroll;
    status.textContent = busy && !autoLoading ? "Loading events…" : history ? "History view · live refresh paused. Refresh newest to return."
      : loaded ? "Newest events first · live refresh every 5 seconds." : "Connecting to log history…";
    actions.hidden = Boolean(commandBand) && !history && (!busy || autoLoading);
    error.textContent = failure; refresh.disabled = busy && !autoLoading;
    older.disabled = busy && !autoLoading || !more || !records.length;
    older.textContent = busy && !autoLoading ? "Loading…" : more ? "Load older events" : "End of retained history";
  }
  async function load(olderPage = false, automatic = false) {
    if (closed || busy || automatic && (history || document.hidden)) return;
    busy = true; autoLoading = automatic; failure = ""; render();
    const controller = new AbortController(); controllers.add(controller);
    const timeout = setTimeout(() => controller.abort(), 15000);
    try {
      const url = new URL(options.base, location.origin);
      url.searchParams.set("limit", "100");
      if (olderPage && cursor !== undefined) url.searchParams.set(options.beforeParam || "before_id", String(cursor));
      const response = await fetch(url, { credentials: "same-origin", cache: "no-store", signal: controller.signal });
      const body = await response.json();
      if (!response.ok) throw new Error(typeof body.error === "string" ? body.error : body.error?.message || body.message || body.detail || "Log history is unavailable");
      const page = Array.isArray(body) ? body : body.events || body.items;
      if (!Array.isArray(page)) throw new Error("The log endpoint returned an invalid page");
      const batch = page.map(normalize);
      if (batch.some(item => item.id === undefined || item.cursor === undefined)) throw new Error("The log endpoint omitted a stable event cursor");
      if (closed) return;
      const saved = automatic || olderPage ? anchor() : { scroll: 0 };
      if (olderPage) {
        if (batch.length && String(batch.at(-1).cursor) === String(cursor)) throw new Error("Log cursor did not advance. Refresh newest to recover.");
        const existing = new Set(records.map(item => String(item.id)));
        records = [...records, ...batch.filter(item => !existing.has(String(item.id)))].slice(-1000);
        history = true;
      } else {
        const seen = new Set();
        records = (automatic ? [...batch, ...records] : batch).filter(item => { const id = String(item.id); if (seen.has(id)) return false; seen.add(id); return true; }).slice(0, 1000);
        history = false;
      }
      render(saved);
      if (records.length) cursor = records.at(-1).cursor;
      more = batch.length === 100; loaded = true;
    } catch (errorValue) {
      if (!closed) { failure = errorValue.message; loaded = true; }
    } finally { clearTimeout(timeout); controllers.delete(controller); busy = false; autoLoading = false; render(); }
  }
  refresh.onclick = () => void load(); older.onclick = () => void load(true);
  const timer = setInterval(() => void load(false, true), 5000);
  void load();
  return () => { closed = true; stopGeometry(); download.remove(); clearInterval(timer); controllers.forEach(controller => controller.abort()); root.replaceChildren(); };
}
