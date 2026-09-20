// Service-owned backup controls. Vendored with the same protocol in each head.
function node(tag, text, className) {
  const item = document.createElement(tag);
  if (text !== undefined) item.textContent = String(text);
  if (className) item.className = className;
  return item;
}

export function mountBackupPolicy(root, options) {
  root.classList.add("exo-backup-policy");
  let closed = false, policy, jobs = [], busy = false, loading = false, timer, failure = "", pending;
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
  function render(force = false) {
    if (closed) return;
    // Do not destroy an active text field during background polling.
    if (!force && root.contains(document.activeElement) && document.activeElement.matches("input[type=number]")) return;
    root.replaceChildren();
    const error = node("p", failure, "exo-agent-error"); error.setAttribute("role", "alert");
    if (!policy) {
      root.append(node("p", loading ? "Loading backup policy…" : "Backup policy is unavailable. Initialize Neptune or update it to a compatible version."), error,
        action("Retry policy status", refresh));
      return;
    }
    const applied = !failure && policy.appliedRevision === policy.revision;
    root.append(node("p", policy.paused ? "Restored policy · pending verification. Execution is paused."
      : applied ? "Schedule applied · revision " + policy.revision
      : "Policy saved · pending application (desired " + policy.revision + ", applied " + policy.appliedRevision + ")",
    policy.paused || !applied ? "exo-agent-muted" : "exo-agent-success"));
    if (policy.paused) root.append(action("Verify and resume restored policy", () => mutate({
      kind: "resume", expectedRevision: policy.revision, requestId: crypto.randomUUID(),
    })));
    root.append(error);
    for (const kind of ["archive", "mirror"]) {
      const settings = policy[kind]; if (!settings) continue;
      const current = kind === "mirror" ? settings.intervalMinutes / 60 : settings.intervalHours;
      const draft = draftFor(kind, current), group = node("section", undefined, "exo-agent-group");
      group.append(node("h3", kind === "archive" ? "Automatic recovery archive" : "Automatic dedicated mirror"));
      const controls = node("div", undefined, "exo-policy-controls");
      const enableLabel = node("label", undefined, "exo-policy-toggle");
      const checkbox = node("input"); checkbox.type = "checkbox"; checkbox.checked = settings.enabled;
      checkbox.disabled = busy || policy.paused; checkbox.setAttribute("aria-label", "Enable automatic backups · " + kind);
      enableLabel.append(checkbox, node("span", "Enable automatic backups"));
      checkbox.onchange = () => void mutate({ kind: "schedule", pipeline: kind, enabled: checkbox.checked,
        intervalHours: current, expectedRevision: policy.revision, requestId: crypto.randomUUID() });
      const intervalLabel = node("label", undefined, "exo-policy-interval");
      const input = node("input"); input.type = "number"; input.min = "1"; input.step = "1";
      input.max = kind === "mirror" ? "168" : "8760"; input.value = draft.value; input.disabled = busy || policy.paused;
      input.setAttribute("aria-label", "Interval in hours · " + kind); input.setAttribute("aria-invalid", String(Boolean(draft.error)));
      const inlineError = node("span", draft.error, "exo-agent-error"); inlineError.setAttribute("role", "alert");
      intervalLabel.append(node("span", "Interval in hours"), input, inlineError);
      input.oninput = () => {
        if (!draft.dirty) draft.revision = policy.revision;
        draft.dirty = true; draft.value = input.value; draft.error = "";
        inlineError.textContent = ""; input.setAttribute("aria-invalid", "false");
      };
      const commit = () => {
        if (busy || !draft.dirty) return;
        if (draft.review) return;
        const value = Number(draft.value), max = kind === "mirror" ? 168 : 8760;
        if (!draft.value.trim() || !Number.isInteger(value) || value < 1 || value > max) {
          draft.error = "Enter a whole number of hours from 1 to " + max + ".";
          inlineError.textContent = draft.error; input.setAttribute("aria-invalid", "true"); return;
        }
        void mutate({ kind: "schedule", pipeline: kind, enabled: settings.enabled, intervalHours: value,
          expectedRevision: draft.revision, requestId: crypto.randomUUID() }, kind);
      };
      input.onkeydown = event => { if (event.key === "Enter") { event.preventDefault(); commit(); } };
      input.onblur = () => { commit(); if (!busy) render(); };
      controls.append(enableLabel, intervalLabel);
      const run = action(kind === "archive" ? "Back up to Saturn now" : "Mirror to Saturn now", () => mutate(
        { pipeline: kind, requestId: crypto.randomUUID() }, undefined, "/runs", "POST"));
      const recent = jobs.find(job => job.kind === kind + ".run" || job.pipeline === kind);
      run.disabled ||= policy.paused || recent?.state === "pending";
      controls.append(run); group.append(controls);
      if (kind === "mirror" && !Number.isInteger(current))
        group.append(node("p", "Imported interval: " + settings.intervalMinutes + " minutes. It is preserved exactly; enter whole hours only when changing it.", "exo-agent-muted"));
      const observed = policy.observed?.[kind] ?? {};
      group.append(node("p", "Next run: " + stamp(observed.nextRunAt) + " · Last successful commitment: " + stamp(observed.lastSuccessAt), "exo-agent-muted"));
      group.append(node("p", "Pipeline state: " + (observed.state || "Not reported") + (observed.error ? " · " + observed.error : "")));
      if (recent) group.append(node("p", "Run " + recent.id + " · " + recent.state + (recent.error ? " · " + recent.error : ""), "exo-agent-job"));
      if (draft.dirty && draft.error) group.append(action("Discard interval draft", () => { drafts.delete(kind); render(); }));
      if (draft.review) {
        group.append(node("p", "Current interval: " + current + " hours. Your proposed interval: " + draft.value + " hours."));
        group.append(action("Apply reviewed interval", () => {
          draft.review = false; draft.revision = policy.revision; commit();
        }));
      }
      root.append(group);
    }
  }
  async function mutate(body, draftKind, suffix = "", method = "PUT") {
    if (busy || closed) return;
    busy = true; failure = ""; remember({ body, suffix, method, draftKind });
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
      failure = error.message;
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
    jobs = Array.isArray(history) ? history : history.jobs ?? [];
  }
  async function refresh() {
    if (loading || busy || closed) return;
    if (pending) { await mutate(pending.body, pending.draftKind, pending.suffix, pending.method); return; }
    loading = true;
    try { await load(); failure = ""; }
    catch (error) { if (!closed) failure = error.message; }
    finally { loading = false; render(); }
  }
  void (async () => {
    if (pending?.body?.requestId && ["PUT", "POST"].includes(pending.method) && ["", "/runs"].includes(pending.suffix))
      await mutate(pending.body, pending.draftKind, pending.suffix, pending.method);
    else await refresh();
  })();
  timer = setInterval(() => void refresh(), 5000);
  render();
  return () => { closed = true; clearInterval(timer); controllers.forEach(controller => controller.abort()); };
}
