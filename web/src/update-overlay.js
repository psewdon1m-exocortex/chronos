// Exocortex update UI protocol 2. Keep the vendored copies identical across heads.
const terminal = new Set(["COMPLETED", "FAILED", "ROLLED_BACK", "ROLLBACK_FAILED"]);


function element(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = String(text);
  if (className) node.className = className;
  return node;
}
function button(text, action, className) {
  const node = element("button", text, className); node.type = "button"; node.addEventListener("click", action); return node;
}
function meta(entries) {
  const list = element("dl", undefined, "meta");
  for (const [key, value] of entries) list.append(element("dt", key), element("dd", value ?? "—"));
  return list;
}
function modal(title, theme, warning = false) {
  const dialog = element("dialog", undefined, `exo-update ${theme ?? ""}${warning ? " warning-dialog" : ""}`);
  const heading = element("h2", title); heading.id = `update-${crypto.randomUUID()}`;
  dialog.setAttribute("aria-labelledby", heading.id);
  const header = element("header"); const close = button("×", () => dialog.close(), "close"); close.setAttribute("aria-label", "Close updates");
  header.append(heading, close); const content = element("div", undefined, "exo-update-content"); dialog.append(header, content);
  document.body.append(dialog); dialog.showModal(); close.focus();
  dialog.addEventListener("click", (event) => { if (event.target === dialog) { const box = dialog.getBoundingClientRect(); if (event.clientX < box.left || event.clientX > box.right || event.clientY < box.top || event.clientY > box.bottom) dialog.close(); } });
  return { dialog, content, close };
}
export function updateCookieHeaders(names, header) {
  const cookie = document.cookie.split(/;\s*/).find((part) => names.some((name) => part.startsWith(`${name}=`)));
  return cookie ? { [header]: decodeURIComponent(cookie.slice(cookie.indexOf("=") + 1)) } : {};
}

export function openUpdateOverlay(options) {
  document.querySelectorAll("dialog.exo-update").forEach((dialog) => dialog.close());
  const { component, service, base } = options;
  const label = component[0].toUpperCase() + component.slice(1);
  const key = `exocortex.update.v2.${service}.${component}`;
  const focusBefore = document.activeElement;
  const view = modal(component === service ? "Updates" : `${label} updates`, options.theme);
  let closed = false, checking = false, installing = false, discovery, job, error = "", connection = "", timer, warning;
  const controllers = new Set();
  let remembered; try { remembered = JSON.parse(localStorage.getItem(key) || "null"); } catch { /* a malformed local hint is disposable */ }
  function remember(value) { remembered = value; try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* server jobs also support recovery */ } }
  async function request(path, method = "GET", body, extraHeaders = {}) {
    const abort = new AbortController(); controllers.add(abort); const timeout = setTimeout(() => abort.abort(), 95000);
    try {
      const headers = { ...(options.headers?.() ?? {}), ...extraHeaders };
      if (body && !(body instanceof Blob) && !(body instanceof ArrayBuffer)) { headers["Content-Type"] = "application/json"; body = JSON.stringify(body); }
      const response = await fetch(base + path, { method, body, headers, credentials: "same-origin", cache: "no-store", signal: abort.signal });
      if (!response.ok) { const data = await response.json().catch(() => ({})); const failure = new Error(data.error || data.message || (typeof data.detail === "string" ? data.detail : "") || `Request failed (HTTP ${response.status})`); failure.status = response.status; throw failure; }
      return response;
    } finally { clearTimeout(timeout); controllers.delete(abort); }
  }
  const json = async (...args) => (await request(...args)).json();
  const active = () => !!job && !terminal.has(job.state);
  function render() {
    if (closed) return;
    const c = view.content; c.replaceChildren();
    c.append(meta([["Installed", discovery?.installed_version ?? options.installedVersion ?? "Checking…"], ["Updater", discovery ? (discovery.updater_label ?? `Available ${discovery.updater_version}`) : "Checking…"], ["Registry", discovery ? "Checked" : error ? "Unavailable" : "Checking…"]]));
    const box = element("section", undefined, "box"); box.append(element("h3", "Discovery"));
    const summary = checking ? "Checking for updates…" : discovery?.update_available ? `${label} ${discovery.available_version} is available.` : discovery ? "No new updates are available." : "Release discovery is unavailable.";
    box.append(element("p", summary));
    box.append(element("p", "GitHub release identity and semantic version are checked here. Artifact digests and health are verified by the privileged updater during installation.", "muted"));
    if (discovery?.release_url) { try { const url = new URL(discovery.release_url); if (url.protocol === "https:" && url.hostname === "github.com") { const link = element("a", "Release notes"); link.href = url.href; link.target = "_blank"; link.rel = "noopener noreferrer"; box.append(link); } } catch { /* invalid metadata is never used as a link */ } }
    c.append(box);
    const actions = element("div", undefined, "actions");
    const again = button("Check again", () => void check()); again.disabled = checking || installing || active(); actions.append(again);
    if (discovery?.update_available) { const install = button(`Install ${discovery.available_version}`, () => component === service ? backupWarning(discovery.available_version) : void installHelper(discovery.available_version)); install.disabled = checking || installing || active(); actions.append(install); }
    c.append(actions);
    const fault = element("p", error, "error"); fault.setAttribute("role", "alert"); c.append(fault);
    if (job || installing || connection) {
      const status = element("section", undefined, "box job"); status.setAttribute("aria-live", "polite");
      status.append(meta([["State", job?.state ?? "REQUESTED"], ["Job", job?.id ?? "Waiting for acknowledgement"], ["Message", job?.message ?? "Submitting the selected release"]]));
      const progress = element("progress"); progress.max = 1; progress.setAttribute("aria-label", "Update progress");
      if (job && terminal.has(job.state)) progress.value = ["COMPLETED", "ROLLED_BACK"].includes(job.state) ? 1 : 0;
      status.append(progress);
      if (job && !terminal.has(job.state)) status.append(element("p", "This phase does not report a measured percentage. Status refreshes automatically.", "muted"));
      if (connection) status.append(element("p", connection, "error"));
      c.append(status);
      if (job && terminal.has(job.state) && job.rollback_available && component === service) rollbackControls(c);
    }
  }
  async function check() {
    if (checking || closed) return;
    checking = true; error = ""; render();
    try { discovery = await json("/check", "POST", { component }); }
    catch (failure) { discovery = undefined; error = failure.message; }
    finally { checking = false; render(); }
  }
  async function poll() {
    if (closed || !job) return;
    try {
      job = await json(`/jobs/${encodeURIComponent(job.id)}`); connection = ""; remember({ id: job.id, request_id: job.request_id }); render();
      if (terminal.has(job.state)) { installing = false; await check(); try { await options.onComplete?.(); } catch (failure) { connection = `Update status received; page refresh failed: ${failure.message}`; render(); } return; }
    } catch (failure) {
      connection = failure.status === 401 || failure.status === 403 ? "Your session has expired. Sign in again, then reopen Updates to resume status." : `Connection interrupted. Reconnecting… ${failure.message}`;
      render(); if (failure.status === 401 || failure.status === 403) return;
    }
    timer = setTimeout(poll, 1500);
  }
  function matching(item) { return item.service === (component === service ? service : component === "updater" ? "updater-self-update" : `${component}-update`); }
  async function recover() {
    try {
      const { jobs = [] } = await json("/jobs");
      job = jobs.find((item) => matching(item) && ((remembered?.id && item.id === remembered.id) || (remembered?.request_id && item.request_id === remembered.request_id)))
        ?? jobs.filter(matching).sort((a, b) => b.created_at.localeCompare(a.created_at)).find((item) => !terminal.has(item.state));
      if (job) { render(); await poll(); }
    } catch (failure) { connection = `Cannot restore update status: ${failure.message}`; render(); }
  }
  async function submit(version, archive, receipt, requestID) {
    installing = true; error = ""; job = undefined; remember({ request_id: requestID }); render();
    try {
      job = archive ? await json(`/install/${component}`, "POST", archive, { "Content-Type": "application/octet-stream", "X-Update-Receipt": receipt, "X-Update-Saved": "1" })
        : await json(`/install/${component}`, "POST", { version, request_id: requestID });
      remember({ id: job.id, request_id: requestID }); void poll();
    } catch (failure) { error = `${failure.message}. Checking whether the updater accepted the request…`; await recover(); }
    finally { installing = false; render(); }
  }
  async function installHelper(version) { await submit(version, undefined, undefined, crypto.randomUUID()); }
  function backupWarning(version) {
    if (warning) return;
    warning = modal(`Install ${service.toUpperCase()} update`, options.theme, true);
    const w = warning; const explanation = element("div", undefined, "warning");
    explanation.append(element("h3", `Install ${service.toUpperCase()} ${version}?`), element("p", "A full backup is created and downloaded first. The updater then verifies artifacts, preserves volumes, checks service health and exposes rollback when available."));
    const actions = element("div", undefined, "actions"); const fault = element("p", "", "error"); fault.setAttribute("role", "alert");
    const cancel = button("Cancel", () => w.dialog.close()); let busy = false, archive, receipt, id;
    const create = button("Create backup and install", async () => {
      if (busy) return; busy = true; create.disabled = true; fault.textContent = "";
      let handle;
      try {
        // The picker must be opened inside the user's activation, before fetching.
        if (window.showSaveFilePicker) handle = await window.showSaveFilePicker({ suggestedName: `${service}-before-${version}.zip`, types: [{ description: "ZIP backup", accept: { "application/zip": [".zip"] } }] });
        create.textContent = "Creating backup…";
        const response = await request("/backup", "POST", { version });
        receipt = response.headers.get("X-Update-Receipt");
        if (!receipt) throw new Error("The server did not return a signed backup receipt");
        const payload = JSON.parse(atob(receipt.split(".")[0].replace(/-/g, "+").replace(/_/g, "/")));
        archive = await response.blob();
        const hash = Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", await archive.arrayBuffer())), (byte) => byte.toString(16).padStart(2, "0")).join("");
        if (archive.size !== payload.size || hash !== payload.sha256) throw new Error("Downloaded ZIP checksum does not match the receipt");
        id = payload.id;
        if (!w.dialog.open) return;
        if (handle) { create.textContent = "Saving backup…"; const file = await handle.createWritable(); try { await file.write(archive); await file.close(); } catch (failure) { await file.abort().catch(() => {}); throw failure; } if (!w.dialog.open || closed) return; w.dialog.close(); await submit(version, archive, receipt, id); }
        else {
          const url = URL.createObjectURL(archive); const link = element("a"); link.href = url; link.download = payload.filename; document.body.append(link); link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(url), 60000);
          create.remove();
          w.content.insertBefore(element("p", "The download has started. Verify that the ZIP is saved on your computer before continuing. A browser download request alone cannot confirm this."), actions);
          const confirm = element("label", undefined, "saved"); const checkbox = element("input"); checkbox.type = "checkbox"; confirm.append(checkbox, element("span", "I have saved the ZIP on my computer.")); w.content.insertBefore(confirm, actions);
          const install = button(`Install ${version}`, () => { w.dialog.close(); void submit(version, archive, receipt, id); }, "danger"); install.disabled = true;
          checkbox.addEventListener("change", () => { install.disabled = !checkbox.checked; }); actions.append(install);
        }
      } catch (failure) { if (failure.name !== "AbortError") fault.textContent = failure.message; create.disabled = false; create.textContent = "Create backup and install"; }
      finally { busy = false; }
    }, "danger");
    actions.append(cancel, create); w.content.append(explanation, fault, actions);
    w.dialog.addEventListener("close", () => { w.dialog.remove(); warning = undefined; if (!closed) view.close.focus(); });
  }
  function rollbackControls(parent) {
    const details = element("details", undefined, "rollback"); details.append(element("summary", "Rollback"), element("p", "Choose the original pre-update ZIP saved on your computer. Its checksum must match this job. No backup archive is retained on the server.", "muted"));
    const file = element("input"); file.type = "file"; file.accept = ".zip,application/zip"; file.setAttribute("aria-label", "Saved pre-update ZIP");
    const restore = button("Restore this version", async () => { const archive = file.files?.[0]; if (!archive) return; restore.disabled = true; error = ""; try { job = await json(`/jobs/${job.id}/rollback`, "POST", archive, { "Content-Type": "application/octet-stream" }); render(); void poll(); } catch (failure) { error = failure.message; render(); } }, "danger");
    restore.disabled = true; const confirm = element("label", undefined, "saved"); const checkbox = element("input"); checkbox.type = "checkbox"; confirm.append(checkbox, element("span", "Restore the previous version and replace current data with this ZIP."));
    const change = () => { restore.disabled = !file.files?.length || !checkbox.checked; }; file.addEventListener("change", change); checkbox.addEventListener("change", change);
    details.append(file, confirm, restore); parent.append(details);
  }
  view.dialog.addEventListener("close", () => { closed = true; clearTimeout(timer); warning?.dialog.close(); controllers.forEach((controller) => controller.abort()); view.dialog.remove(); focusBefore?.focus?.(); });
  render(); void check(); void recover();
  return () => view.dialog.close();
}
