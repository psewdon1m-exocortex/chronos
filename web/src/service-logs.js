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
  return {
    id: event.id ?? event.event_id ?? event.sequence,
    cursor: event.sequence ?? event.id ?? event.event_id,
    timestamp: event.occurredAt ?? event.occurred_at ?? event.created_at ?? event.at ?? event.timestamp,
    failed: typeof status === "number" ? status >= 400 : /error|fail|denied|reject|critical/i.test(status),
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
  let records = [], cursor, more = true, busy = false, closed = false, history = false, failure = "", loaded = false;
  const controllers = new Set();
  const actions = node("div", undefined, "exo-log-actions");
  const download = node("a", "Download archived logs"); download.href = options.download || "#"; if (options.onDownload) download.onclick = event => { event.preventDefault(); options.onDownload(); }; download.setAttribute("download", "");
  const refresh = node("button", "Refresh newest"), older = node("button", "Load older events");
  refresh.type = older.type = "button";
  const status = node("p"); status.setAttribute("role", "status");
  const error = node("p", "", "exo-agent-error"); error.setAttribute("role", "alert");
  const viewport = node("div", undefined, "exo-log-viewport"); viewport.tabIndex = 0; viewport.setAttribute("aria-label", "Service log history");
  const header = node("div", undefined, "exo-log-row exo-log-header");
  for (const label of ["TYPE", "BODY", "TIME"]) header.append(node("span", label));
  actions.append(download, refresh); root.replaceChildren(actions, status, error, viewport, older);
  function render() {
    if (closed) return;
    const scroll = viewport.scrollTop;
    viewport.replaceChildren(header);
    if (!records.length) viewport.append(node("p", !loaded ? "Loading events…" : "No retained events."));
    for (const record of records) {
      const row = node("div", undefined, "exo-log-row");
      const time = node("time", timestamp(record.timestamp)); time.title = "Local browser time";
      row.append(node("strong", record.failed ? "/ERROR" : "/INFO", record.failed ? "exo-agent-error" : "exo-agent-success"),
        node("span", record.body), time); viewport.append(row);
    }
    viewport.scrollTop = scroll;
    status.textContent = busy ? "Loading events…" : history ? "History view · live refresh paused. Refresh newest to return."
      : loaded ? "Newest events first · live refresh every 5 seconds." : "Connecting to log history…";
    error.textContent = failure; refresh.disabled = busy;
    older.disabled = busy || !more || !records.length;
    older.textContent = busy ? "Loading…" : more ? "Load older events" : "End of retained history";
  }
  async function load(olderPage = false, automatic = false) {
    if (closed || busy || automatic && (history || document.hidden)) return;
    busy = true; failure = ""; render();
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
      if (olderPage) {
        if (batch.length && String(batch.at(-1).cursor) === String(cursor)) throw new Error("Log cursor did not advance. Refresh newest to recover.");
        const existing = new Set(records.map(item => String(item.id)));
        records = [...records, ...batch.filter(item => !existing.has(String(item.id)))].slice(-1000);
        history = true;
      } else { records = batch; history = false; viewport.scrollTop = 0; }
      if (batch.length) cursor = batch.at(-1).cursor;
      more = batch.length === 100; loaded = true;
    } catch (errorValue) {
      if (!closed) { failure = errorValue.message; loaded = true; }
    } finally { clearTimeout(timeout); controllers.delete(controller); busy = false; render(); }
  }
  refresh.onclick = () => void load(); older.onclick = () => void load(true);
  const timer = setInterval(() => void load(false, true), 5000);
  void load();
  return () => { closed = true; clearInterval(timer); controllers.forEach(controller => controller.abort()); root.replaceChildren(); };
}
