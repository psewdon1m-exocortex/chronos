// A read-only open/preflight precedes the explicit typed initialization action.
function node(tag, text, className) {
  const item = document.createElement(tag);
  if (text !== undefined) item.textContent = String(text);
  if (className) item.className = className;
  return item;
}
export function openAgentInitialization(options) {
  const focusBefore = document.activeElement;
  const dialog = node("dialog", undefined, "exo-update exo-initialize " + (options.theme || ""));
  const header = node("header"), title = node("h2", "Initialize " + options.component);
  title.id = "initialize-" + crypto.randomUUID(); dialog.setAttribute("aria-labelledby", title.id);
  const close = node("button", "×", "close"); close.type = "button"; close.setAttribute("aria-label", "Close initialization");
  close.onclick = () => dialog.close(); header.append(title, close);
  const content = node("div", undefined, "exo-update-content"), form = node("form");
  const summary = node("p", options.description), context = node("p", options.profile || "", "muted");
  const feedback = node("p", "", "exo-agent-result"); feedback.setAttribute("role", "status");
  const error = node("p", "", "error"); error.setAttribute("role", "alert");
  const controls = node("div", undefined, "actions"), cancel = node("button", "Cancel"), submit = node("button", "Initialize");
  cancel.type = "button"; cancel.onclick = () => dialog.close(); submit.type = "submit"; submit.disabled = true;
  controls.append(cancel, submit);
  let code;
  if (options.codeLabel) {
    const label = node("label"); code = node("input");
    code.type = "password"; code.autocomplete = "off"; code.spellcheck = false;
    code.minLength = 32; code.maxLength = 32; code.required = true;
    code.setAttribute("aria-label", options.codeLabel);
    label.append(node("span", options.codeLabel), code);
    form.append(label);
  }
  form.append(controls); content.append(summary, context, feedback, form, error); dialog.append(header, content);
  const key = "exocortex.initialize.v1." + options.service + "." + options.component;
  let hint; try { hint = JSON.parse(localStorage.getItem(key) || "null"); } catch { /* Server jobs are authoritative. */ }
  let job, panel, timer, closed = false, submitting = false, verifying = false, verified = false;
  const terminal = new Set(["COMPLETED", "FAILED", "ROLLED_BACK", "ROLLBACK_FAILED"]);
  function remember(value) {
    hint = value;
    try { if (value) localStorage.setItem(key, JSON.stringify(value)); else localStorage.removeItem(key); } catch { /* No secrets in this hint. */ }
  }
  function showJob() {
    panel?.remove(); panel = node("section", undefined, "box job"); panel.setAttribute("aria-live", "polite");
    const state = verifying ? "VERIFYING_CONNECTION" : verified ? "VERIFIED" : job?.state || "REQUESTED";
    for (const [label, value] of [["Job", job?.id || job?.job_id || hint?.id || "Awaiting acknowledgement"],
      ["State", state], ["Message", job?.message || job?.error || "The accepted operation continues on the host"]]) {
      const row = node("p"); row.append(node("strong", label + ": "), node("span", value)); panel.append(row);
    }
    const progress = node("progress"); progress.max = 1; progress.setAttribute("aria-label", "Initialization progress");
    const measured = job?.progress;
    if (verified) progress.value = 1;
    else if (measured?.mode === "determinate" && Number.isFinite(measured.completed) && Number.isFinite(measured.total)
      && measured.total > 0 && measured.completed >= 0 && measured.completed <= measured.total)
      progress.value = measured.completed / measured.total;
    panel.append(progress);
    if (!verified) panel.append(node("p", "Closing this window stops observation only. Reopen Initialize to continue viewing this job.", "muted"));
    content.append(panel);
  }
  async function verify() {
    if (closed || verifying) return;
    verifying = true; submit.disabled = true; feedback.textContent = "Checking enrollment and every required pipeline…"; showJob();
    try {
      const result = await options.verify();
      if (closed) return;
      verified = result.ready === true;
      if (!verified) throw new Error(result.message || "Installation completed, but the scoped connection is not ready. Review status and repair the missing configuration.");
      feedback.textContent = "Connection and required functions verified."; error.textContent = "";
      if (code) code.value = "";
      form.hidden = true; await options.onComplete?.();
    } catch (failure) {
      if (!closed) {
        error.textContent = failure.message; feedback.textContent = "Pending verification";
        form.hidden = false; submit.disabled = false; submit.textContent = "Repair connection";
      }
    } finally { verifying = false; if (!closed) showJob(); }
  }
  async function observe() {
    if (closed || !job) return;
    try {
      const next = await options.observe(job.id || job.job_id || hint?.id);
      if (closed) return;
      job = next; remember({ id: job.id || job.job_id || hint?.id, request_id: job.request_id || hint?.request_id });
      error.textContent = ""; showJob();
      if (job.state === "COMPLETED") { await verify(); return; }
      if (terminal.has(job.state)) {
        feedback.textContent = "Initialization failed"; error.textContent = job.message || job.error || "The helper could not initialize this service";
        form.hidden = false; submit.disabled = false; submit.textContent = "Retry initialization"; remember(null); return;
      }
    } catch (failure) {
      if (closed) return;
      error.textContent = failure.message;
      feedback.textContent = failure.status === 401 || failure.status === 403 ? "Sign in again, then reopen this job." : "Connection interrupted. Retrying observation…";
      if (failure.status === 401 || failure.status === 403) return;
    }
    timer = setTimeout(() => void observe(), 1500);
  }
  async function recover() {
    const found = await options.recover?.(hint);
    if (closed) return false;
    if (found && (found.id || found.job_id) && found.state !== "IDLE") {
      job = found; submit.disabled = true; if (code) code.value = "";
      form.hidden = true; showJob(); await observe(); return true;
    }
    return false;
  }
  form.onsubmit = async event => {
    event.preventDefault();
    if (submitting || verifying || job && !terminal.has(job.state)) return;
    if (code && !/^[A-Za-z0-9_-]{32}$/.test(code.value.trim())) {
      error.textContent = "Enter the 32-character setup code."; return;
    }
    submitting = true; submit.disabled = true; error.textContent = ""; verified = false;
    const requestID = job && terminal.has(job.state) ? crypto.randomUUID() : hint?.request_id || crypto.randomUUID(); remember({ request_id: requestID });
    const input = { request_id: requestID, ...(code ? { enrollment_code: code.value.trim() } : {}) };
    feedback.textContent = "Submitting initialization…";
    try {
      const accepted = await options.initialize(input);
      if (code) code.value = "";
      if (closed) return;
      job = accepted; remember({ id: accepted.id || accepted.job_id, request_id: accepted.request_id || requestID });
      form.hidden = true; showJob(); void observe();
    } catch (failure) {
      if (closed) return;
      error.textContent = failure.message;
      feedback.textContent = "Checking whether the operation was accepted…";
      try { if (await recover()) return; } catch { /* Preserve the request ID for explicit retry. */ }
      if (failure.status && failure.status < 500) remember(null);
      feedback.textContent = "Initialization was not confirmed. Retry uses the same operation ID after an uncertain response.";
      submit.disabled = false;
    } finally { delete input.enrollment_code; submitting = false; }
  };
  const retryStatus = node("button", "Check status"); retryStatus.type = "button";
  retryStatus.onclick = () => {
    clearTimeout(timer);
    if (job?.state === "COMPLETED") void verify();
    else if (job) void observe();
    else void recover().catch(failure => { if (!closed) error.textContent = failure.message; });
  };
  content.append(retryStatus);
  dialog.addEventListener("close", () => {
    closed = true; clearTimeout(timer); if (code) code.value = "";
    dialog.remove(); if (focusBefore?.isConnected) focusBefore.focus();
  });
  document.body.append(dialog); dialog.showModal(); close.focus();
  void (async () => {
    try {
      if (await recover()) return;
      const result = await options.verify();
      if (closed) return;
      feedback.textContent = result.ready ? "This service is already connected and verified." : result.message || "Ready for explicit initialization.";
      submit.disabled = result.ready;
    } catch (failure) {
      if (!closed) { feedback.textContent = "Preflight is unavailable; initialization will validate the target."; error.textContent = failure.message; submit.disabled = false; }
    }
  })();
  return () => { if (!closed) dialog.close(); };
}

export function confirmAgentAction({ title, message, confirmLabel, theme = "" }) {
  return new Promise(resolve => {
    const previous = document.activeElement;
    const dialog = node("dialog", undefined, "exo-update exo-initialize " + theme);
    const header = node("header"), heading = node("h2", title);
    heading.id = "confirm-" + crypto.randomUUID(); dialog.setAttribute("aria-labelledby", heading.id);
    header.append(heading);
    const body = node("div", undefined, "exo-update-content"), actions = node("div", undefined, "actions");
    const cancel = node("button", "Cancel"), accept = node("button", confirmLabel, "danger");
    cancel.type = accept.type = "button"; cancel.onclick = () => dialog.close();
    accept.onclick = () => dialog.close("confirmed");
    actions.append(cancel, accept); body.append(node("p", message), actions); dialog.append(header, body);
    dialog.addEventListener("close", () => {
      const confirmed = dialog.returnValue === "confirmed"; dialog.remove();
      if (previous?.isConnected) previous.focus(); resolve(confirmed);
    }, { once: true });
    document.body.append(dialog); dialog.showModal(); cancel.focus();
  });
}
