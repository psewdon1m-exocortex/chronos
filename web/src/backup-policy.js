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
  let closed = false, policy, jobs = [], busy = false, loading = false, timer, failure = "", failureCode = "", pending;
  const drafts = new Map(), controllers = new Set();
  const key = "exocortex.backup-policy.v1." + options.service;
  try { pending = JSON.parse(localStorage.getItem(key) || "null"); } catch { /* Only an operation hint. */ }
  const remember = value => {
    pending = value;
    try { if (value) localStorage.setItem(key, JSON.stringify(value)); else localStorage.removeItem(key); } catch { /* Server replay is authoritative. */ }
  };
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
  const stopGeometry = bindActionGeometry(root);
  const summary = node("p", "", "exo-policy-summary"), error = node("p", "", "exo-agent-error");
  error.setAttribute("role", "alert"); summary.setAttribute("role", "status");
  const retry = action("Retry policy status", refresh);
  const resume = action("Verify and resume restored policy", () => mutate({ kind: "resume", expectedRevision: policy.revision, requestId: crypto.randomUUID() }));
  root.replaceChildren(summary, error, retry, resume);
  const panels = new Map();
  function makePanel(kind) {
    const group = node("section", undefined, "exo-agent-group"), controls = node("div", undefined, "exo-policy-controls");
    group.dataset.pipeline = kind;
    const toggle = node("label", undefined, "exo-policy-toggle"), checkbox = node("input"); checkbox.type = "checkbox";
    checkbox.setAttribute("aria-label", "Enable automatic backups · " + kind);
    toggle.append(checkbox, node("span", "Enable automatic backups"));
    const label = node("label", undefined, "exo-policy-interval"), input = node("input");
    input.type = "number"; input.min = "1"; input.step = "1"; input.max = kind === "mirror" ? "168" : "8760";
    input.setAttribute("aria-label", "Interval in hours · " + kind);
    const inlineError = node("span", "", "exo-agent-error"); inlineError.id = "interval-error-" + crypto.randomUUID();
    inlineError.setAttribute("role", "alert"); input.setAttribute("aria-describedby", inlineError.id);
    label.append(node("span", "Interval in hours"), input, inlineError);
    const current = () => kind === "mirror" ? policy[kind].intervalMinutes / 60 : policy[kind].intervalHours;
    const commit = () => {
      const draft = draftFor(kind, current());
      if (busy || !draft.dirty || draft.review) return;
      const value = Number(draft.value), max = kind === "mirror" ? 168 : 8760;
      if (!draft.value.trim() || !Number.isInteger(value) || value < 1 || value > max) {
        draft.error = "Enter a whole number of hours from 1 to " + max + "."; render(); return;
      }
      void mutate({ kind: "schedule", pipeline: kind, enabled: policy[kind].enabled, intervalHours: value,
        expectedRevision: draft.revision, requestId: crypto.randomUUID() }, kind);
    };
    input.oninput = () => {
      const draft = draftFor(kind, current());
      if (!draft.dirty) draft.revision = policy.revision;
      draft.dirty = true; draft.value = input.value; draft.error = "";
      inlineError.textContent = ""; input.setAttribute("aria-invalid", "false");
    };
    input.onkeydown = event => { if (event.key === "Enter") { event.preventDefault(); commit(); } };
    input.onblur = commit;
    checkbox.onchange = () => void mutate({ kind: "schedule", pipeline: kind, enabled: checkbox.checked,
      intervalHours: current(), expectedRevision: policy.revision, requestId: crypto.randomUUID() });
    const run = action(kind === "archive" ? "Back up to Saturn now" : "Mirror to Saturn now", () => mutate(
      { pipeline: kind, requestId: crypto.randomUUID() }, undefined, "/runs", "POST"));
    controls.append(toggle, label, run);
    const imported = node("p", "", "exo-agent-muted"), observed = node("p", "", "exo-agent-muted"), state = node("p"), job = node("p", "", "exo-agent-job");
    const review = node("p"), discard = action("Discard interval draft", () => { drafts.delete(kind); render(); });
    const apply = action("Apply reviewed interval", () => { const draft = draftFor(kind, current()); draft.review = false; draft.revision = policy.revision; commit(); });
    const heading = node("h3", kind === "archive" ? "Automatic recovery archive" : "Automatic dedicated mirror");
    const details = node("div", undefined, "exo-policy-observations"); details.append(imported, observed, state, job);
    group.append(heading, controls, details, review, discard, apply);
    root.insertBefore(group, summary);
    return { group, heading, input, checkbox, run, inlineError, imported, observed, state, job, review, discard, apply };
  }
  function render() {
    if (closed) return;
    const unconfigured = !policy && failureCode === "NEPTUNE_NOT_CONFIGURED";
    error.textContent = unconfigured ? "" : failure; retry.hidden = unconfigured || !failure; retry.disabled = busy;
    resume.hidden = !policy?.paused; resume.disabled = busy;
    summary.hidden = !policy && !loading && !unconfigured;
    if (!policy) { summary.className = "exo-policy-summary exo-agent-muted"; summary.textContent = unconfigured ? "Initialize Neptune to enable automatic backups." : loading ? "Loading backup policy…" : ""; return; }
    const applied = !failure && policy.appliedRevision === policy.revision;
    summary.textContent = policy.paused ? "Restored policy · pending verification. Execution is paused." : applied ? "Schedule applied · revision " + policy.revision
      : "Policy saved · pending application (desired " + policy.revision + ", applied " + policy.appliedRevision + ")";
    summary.className = "exo-policy-summary " + (policy.paused || !applied ? "exo-agent-muted" : "exo-agent-success");
    for (const kind of ["archive", "mirror"]) {
      if (!policy[kind]) { if (panels.has(kind)) panels.get(kind).group.hidden = true; continue; }
      if (!panels.has(kind)) panels.set(kind, makePanel(kind));
      const panel = panels.get(kind), settings = policy[kind], current = kind === "mirror" ? settings.intervalMinutes / 60 : settings.intervalHours;
      panel.group.hidden = false;
      panel.heading.hidden = !policy.archive || !policy.mirror;
      const draft = draftFor(kind, current);
      panel.checkbox.checked = settings.enabled; panel.checkbox.disabled = busy || policy.paused;
      panel.input.disabled = busy || policy.paused;
      if (document.activeElement !== panel.input) panel.input.value = draft.value;
      panel.input.setAttribute("aria-invalid", String(Boolean(draft.error))); panel.inlineError.textContent = draft.error;
      const recent = jobs.find(job => job.kind === kind + ".run" || job.pipeline === kind);
      panel.run.disabled = busy || policy.paused || recent?.state === "pending";
      panel.imported.hidden = kind !== "mirror" || Number.isInteger(current);
      panel.imported.textContent = "Imported interval: " + settings.intervalMinutes + " minutes. Preserved exactly until you choose whole hours.";
      const observed = policy.observed?.[kind] ?? {};
      panel.observed.textContent = "Next run: " + stamp(observed.nextRunAt) + " · Last successful commitment: " + stamp(observed.lastSuccessAt);
      panel.state.textContent = "Pipeline state: " + (observed.state || "Not reported") + (observed.error ? " · " + observed.error : "");
      panel.job.hidden = !recent; panel.job.textContent = recent ? "Run " + recent.id + " · " + recent.state + (recent.error ? " · " + recent.error : "") : "";
      panel.discard.hidden = !(draft.dirty && draft.error); panel.discard.disabled = busy;
      panel.review.hidden = panel.apply.hidden = !draft.review; panel.apply.disabled = busy;
      panel.review.textContent = "Current interval: " + current + " hours. Your proposed interval: " + draft.value + " hours.";
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
    const history = await request("/runs");
    jobs = Array.isArray(history) ? history : history.jobs ?? history.runs ?? [];
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
    if (pending?.body?.requestId && ["PUT", "POST"].includes(pending.method) && ["", "/runs"].includes(pending.suffix))
      await mutate(pending.body, pending.draftKind, pending.suffix, pending.method);
    else await refresh();
  })();
  timer = setInterval(() => void refresh(), 5000);
  render();
  return () => { closed = true; stopGeometry(); clearInterval(timer); controllers.forEach(controller => controller.abort()); };
}
