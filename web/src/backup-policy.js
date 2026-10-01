import { bindActionGeometry } from "./ui-interactions.js";
// Service-owned backup controls. Vendored with the same protocol in each head.
function node(tag, text, className) {
  const item = document.createElement(tag);
  if (text !== undefined) item.textContent = String(text);
  if (className) item.className = className;
  return item;
}

export function mountBackupPolicy(root, options) {
  root.classList.add("exo-backup-policy");
  let closed = false, policy, busy = false, loading = false, timer, failure = "", failureCode = "", pending;
  const drafts = new Map(), controllers = new Set();
  const key = "exocortex.backup-policy.v1." + options.service;
  try { pending = JSON.parse(localStorage.getItem(key) || "null"); } catch { /* Only an operation hint. */ }
  const remember = value => {
    pending = value;
    try { if (value) localStorage.setItem(key, JSON.stringify(value)); else localStorage.removeItem(key); } catch { /* Server replay is authoritative. */ }
  };
  if (pending && (pending.method !== "PUT" || pending.suffix !== "")) remember(null);
  async function request(suffix = "", method = "GET", body) {
    const controller = new AbortController(); controllers.add(controller);
    const timeout = setTimeout(() => controller.abort(), 25000);
    try {
      const response = await fetch(options.base + suffix, {
        method, credentials: "same-origin", cache: "no-store", signal: controller.signal,
        headers: { ...(options.headers?.() ?? {}), ...(body ? { "Content-Type": "application/json" } : {}) },
        ...(body ? { body: JSON.stringify(body) } : {}),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        const error = new Error((typeof data.error === "string" ? data.error : data.error?.message) || data.message || (typeof data.detail === "string" ? data.detail : "") || "Backup service is unavailable");
        error.status = response.status;
        error.code = data.code || "";
        throw error;
      }
      return data;
    } finally { clearTimeout(timeout); controllers.delete(controller); }
  }
  const stamp = value => value ? new Date(value).toLocaleString(undefined, { hour12: false }) : "Not reported";
  function action(text, run) {
    const button = node("button", text); button.type = "button"; button.disabled = busy;
    button.onclick = () => void run();
    return button;
  }
  function draftFor(kind, current) {
    if (!drafts.has(kind)) drafts.set(kind, { value: String(current), confirmed: current, revision: policy.revision, dirty: false, error: "" });
    const draft = drafts.get(kind);
    if (!draft.dirty) { draft.value = String(current); draft.confirmed = current; draft.revision = policy.revision; }
    return draft;
  }
  const schedule = (enabled, intervalHours, expectedRevision) => ({
    kind: policy.mirror ? "schedule-all" : "schedule",
    ...(policy.mirror ? {} : { pipeline: "archive" }), enabled, intervalHours,
    expectedRevision, requestId: crypto.randomUUID(),
  });
  const stopGeometry = bindActionGeometry(root);
  const summary = node("p", "", "exo-policy-summary"), error = node("p", "", "exo-agent-error");
  error.setAttribute("role", "alert"); summary.setAttribute("role", "status");
  const retry = action("Retry policy status", refresh);
  const resume = action("Verify and resume restored policy", () => mutate({ kind: "resume", expectedRevision: policy.revision, requestId: crypto.randomUUID() }));
  const statuses = node("div", undefined, "exo-policy-statuses");
  const statusRow = label => {
    const row = node("div", undefined, "exo-agent-status exo-policy-status");
    const value = node("strong"); value.append(node("span", "Not verified"), node("i"));
    row.append(node("span", label), value);
    return row;
  };
  const fallbackArchive = statusRow(options.service === "mastermind" ? "Basic pipeline status:" : "Pipeline status:");
  const fallbackMirror = statusRow("Advanced vault pipeline status:");
  fallbackMirror.hidden = options.service !== "mastermind";
  statuses.append(fallbackArchive, fallbackMirror);
  const fallbackControls = node("div", undefined, "exo-policy-controls");
  const fallbackToggle = node("label", undefined, "exo-policy-toggle"), fallbackCheckbox = node("input");
  fallbackCheckbox.type = "checkbox"; fallbackCheckbox.disabled = true;
  fallbackToggle.append(fallbackCheckbox, node("span", "Enable automatic backups"));
  const fallbackInterval = node("label", undefined, "exo-policy-interval"), fallbackInput = node("input");
  fallbackInput.type = "number"; fallbackInput.value = "24"; fallbackInput.disabled = true;
  fallbackInterval.append(node("span", "Interval in hours"), fallbackInput);
  fallbackControls.append(fallbackToggle, fallbackInterval);
  root.replaceChildren(statuses, fallbackControls, summary, error, retry, resume);
  const panels = new Map();
  function makePanel(kind) {
    const group = node("section", undefined, "exo-agent-group"), controls = node("div", undefined, "exo-policy-controls");
    group.dataset.pipeline = kind;
    const toggle = node("label", undefined, "exo-policy-toggle"), checkbox = node("input"); checkbox.type = "checkbox";
    checkbox.setAttribute("aria-label", "Enable automatic backups · " + kind);
    toggle.append(checkbox, node("span", "Enable automatic backups"));
    const label = node("label", undefined, "exo-policy-interval"), input = node("input");
    input.type = "number"; input.min = "1"; input.step = "1"; input.max = policy.mirror ? "168" : "8760";
    input.setAttribute("aria-label", "Interval in hours · " + kind);
    const inlineError = node("span", "", "exo-agent-error"); inlineError.id = "interval-error-" + crypto.randomUUID();
    inlineError.setAttribute("role", "alert"); input.setAttribute("aria-describedby", inlineError.id);
    label.append(node("span", "Interval in hours"), input, inlineError);
    const current = () => policy.archive.intervalHours;
    const commit = () => {
      const draft = draftFor(kind, current());
      if (busy || !draft.dirty || draft.review) return;
      const value = Number(draft.value), max = policy.mirror ? 168 : 8760;
      if (!draft.value.trim() || !Number.isInteger(value) || value < 1 || value > max) {
        draft.error = "Enter a whole number of hours from 1 to " + max + "."; render(); return;
      }
      void mutate(schedule(policy.archive.enabled, value, draft.revision), "archive");
    };
    input.oninput = () => {
      const draft = draftFor(kind, current());
      if (!draft.dirty) draft.revision = policy.revision;
      draft.dirty = true; draft.value = input.value; draft.error = "";
      inlineError.textContent = ""; input.setAttribute("aria-invalid", "false");
    };
    input.onkeydown = event => { if (event.key === "Enter") { event.preventDefault(); commit(); } };
    input.onblur = commit;
    checkbox.onchange = () => {
      if (policy.mirror && current() > 168) { failure = "Choose a shared interval from 1 to 168 hours before changing both pipelines."; render(); return; }
      void mutate(schedule(checkbox.checked, current(), policy.revision));
    };
    controls.append(toggle, label);
    const imported = node("p", "", "exo-agent-muted"), observed = node("p", "", "exo-agent-muted"), state = node("p"), drift = node("p", "", "exo-agent-muted");
    const review = node("p"), discard = action("Discard interval draft", () => { drafts.delete(kind); render(); });
    const apply = action("Apply reviewed interval", () => { const draft = draftFor(kind, current()); draft.review = false; draft.revision = policy.revision; commit(); });
    const heading = statusRow(kind === "archive"
      ? policy.mirror ? "Basic pipeline status:" : "Pipeline status:"
      : "Advanced vault pipeline status:");
    const details = node("div", undefined, "exo-policy-observations"); details.append(imported, observed, state);
    statuses.append(heading);
    if (kind === "archive") group.append(controls, drift, review, discard, apply);
    group.append(details);
    root.insertBefore(group, summary);
    return { group, heading, input, checkbox, inlineError, imported, observed, state, drift, review, discard, apply };
  }
  function render() {
    if (closed) return;
    const unconfigured = !policy && failureCode === "NEPTUNE_NOT_CONFIGURED";
    error.textContent = unconfigured ? "" : failure; retry.hidden = unconfigured || !failure; retry.disabled = busy;
    resume.hidden = !policy?.paused; resume.disabled = busy;
    summary.hidden = !policy && !loading && !unconfigured;
    if (!policy) {
      fallbackArchive.hidden = false; fallbackMirror.hidden = options.service !== "mastermind";
      fallbackControls.hidden = false;
      fallbackArchive.dataset.state = fallbackMirror.dataset.state = "unavailable";
      for (const panel of panels.values()) { panel.heading.hidden = true; panel.group.hidden = true; }
      summary.className = "exo-policy-summary exo-agent-muted"; summary.textContent = unconfigured ? "Initialize Neptune to enable automatic backups." : loading ? "Loading backup policy…" : "";
      return;
    }
    fallbackArchive.hidden = fallbackMirror.hidden = fallbackControls.hidden = true;
    const applied = !failure && policy.appliedRevision === policy.revision;
    summary.textContent = policy.paused ? "Restored policy · pending verification. Execution is paused." : applied ? "Schedule applied · revision " + policy.revision
      : "Policy saved · pending application (desired " + policy.revision + ", applied " + policy.appliedRevision + ")";
    summary.className = "exo-policy-summary " + (policy.paused || !applied ? "exo-agent-muted" : "exo-agent-success");
    for (const kind of ["archive", "mirror"]) {
      if (!policy[kind]) { if (panels.has(kind)) { panels.get(kind).group.hidden = true; panels.get(kind).heading.hidden = true; } continue; }
      if (!panels.has(kind)) panels.set(kind, makePanel(kind));
      const panel = panels.get(kind), settings = policy[kind], current = kind === "mirror" ? settings.intervalMinutes / 60 : settings.intervalHours;
      panel.group.hidden = false;
      panel.heading.hidden = false;
      panel.heading.firstChild.textContent = kind === "archive" ? policy.mirror ? "Basic pipeline status:" : "Pipeline status:" : "Advanced vault pipeline status:";
      if (kind === "archive") {
        const draft = draftFor(kind, current);
        panel.checkbox.checked = settings.enabled; panel.checkbox.indeterminate = Boolean(policy.mirror && settings.enabled !== policy.mirror.enabled);
        panel.checkbox.disabled = busy || policy.paused;
        panel.input.max = policy.mirror ? "168" : "8760";
        panel.input.disabled = busy || policy.paused;
        if (document.activeElement !== panel.input) panel.input.value = draft.value;
        panel.input.setAttribute("aria-invalid", String(Boolean(draft.error))); panel.inlineError.textContent = draft.error;
        panel.drift.hidden = !policy.mirror || settings.enabled === policy.mirror.enabled && settings.intervalHours * 60 === policy.mirror.intervalMinutes;
        panel.drift.textContent = "The two saved schedules differ. Choose an interval and save it to align both pipelines.";
        panel.discard.hidden = !(draft.dirty && draft.error); panel.discard.disabled = busy;
        panel.review.hidden = panel.apply.hidden = !draft.review; panel.apply.disabled = busy;
        panel.review.textContent = "Current interval: " + current + " hours. Your proposed interval: " + draft.value + " hours.";
      }
      panel.imported.hidden = kind !== "mirror" || Number.isInteger(current);
      panel.imported.textContent = "Imported interval: " + settings.intervalMinutes + " minutes. Preserved exactly until you choose whole hours.";
      const observed = policy.observed?.[kind] ?? {};
      const online = policy.observed?.online;
      const unhealthy = Boolean(observed.error) || /error|fail|denied|unavailable/i.test(String(observed.state || ""));
      const ready = online === true && applied && !policy.paused && Boolean(observed.state) && !unhealthy;
      panel.heading.dataset.state = ready ? "ready" : online === undefined ? "busy" : "unavailable";
      panel.heading.querySelector("strong span").textContent = ready ? "Reachability"
        : policy.paused ? "Paused" : online === false ? "Unavailable" : unhealthy ? "Pipeline error"
          : !applied ? "Pending application" : "Not verified";
      panel.observed.textContent = "Next run: " + stamp(observed.nextRunAt) + " · Last successful commitment: " + stamp(observed.lastSuccessAt);
      panel.state.textContent = "Pipeline state: " + (observed.state || "Not reported") + (observed.error ? " · " + observed.error : "");
    }
  }
  async function mutate(body, draftKind, suffix = "", method = "PUT") {
    if (busy || closed) return;
    busy = true; failure = failureCode = ""; remember({ body, suffix, method, draftKind });
    // Disable existing controls without losing focus/draft to a re-render.
    root.querySelectorAll("button,input").forEach(control => { control.disabled = true; });
    try {
      const result = await request(suffix, method, body);
      if (closed) return;
      if (!suffix) policy = result;
      if (draftKind) drafts.delete(draftKind);
      remember(null);
      await load();
    } catch (error) {
      if (closed) return;
      failure = error.message; failureCode = error.code || "";
      if (error.status && error.status < 500) remember(null);
      if (draftKind && drafts.has(draftKind)) {
        drafts.get(draftKind).error = error.status === 409 ? "Policy changed. Your proposed interval is preserved; review before retrying." : error.message;
        drafts.get(draftKind).review = error.status === 409;
      }
      await load().catch(() => {});
    } finally { busy = false; if (!closed) render(true); }
  }
  async function load() {
    const current = await request();
    if (current.schema !== "exocortex.backup.policy.v1") throw new Error("The service-owned backup policy protocol is unavailable");
    policy = current;
  }
  async function refresh() {
    if (loading || busy || closed) return;
    if (pending) { await mutate(pending.body, pending.draftKind, pending.suffix, pending.method); return; }
    loading = true;
    try { await load(); failure = failureCode = ""; }
    catch (error) { if (!closed) { failure = error.message; failureCode = error.code || ""; } }
    finally { loading = false; render(); }
  }
  void (async () => {
    if (pending?.body?.requestId && pending.method === "PUT" && pending.suffix === "")
      await mutate(pending.body, pending.draftKind, pending.suffix, pending.method);
    else await refresh();
  })();
  timer = setInterval(() => void refresh(), 5000);
  render();
  return () => { closed = true; stopGeometry(); clearInterval(timer); controllers.forEach(controller => controller.abort()); };
}
