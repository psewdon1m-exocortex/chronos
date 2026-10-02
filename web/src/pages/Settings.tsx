import { ServiceLogsPanel } from "../ServiceLogsPanel";
import { openAgentInitialization, confirmAgentAction, type InitializationJob } from "../agent-initialize.js";
import { BackupPolicyPanel } from "../service-agents";
import { updateCookieHeaders } from "../update-overlay.js";
const policyHeaders = () => updateCookieHeaders(["chronos_csrf"], "X-CSRF-Token");
import { type FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";

import { api, downloadFile } from "../api";
import { applyTheme, localDate } from "../format";
import type { SettingsResponse, SettingsValues } from "../types";
import { LoadingBlock, Overlay, StatusSquare, SubmitButton, UniversalCard, useNotices } from "../ui";
import { openChronosUpdates } from "../update-flow";

type SettingsKey = SettingsValues["settings_order"][number];
const DEFAULT_ORDER: SettingsKey[] = ["appearance", "security", "backup", "gryphon", "updates", "logs", "personalization"];

interface UpdateStatus {
  service: string;
  installed_version: string;
  repository_url: string | null;
  register_revision: string | null;
  updater: { installed: boolean; available: boolean; status?: string; version?: string; message?: string };
}

interface BackupInspection {
  schema: string;
  created_at: string | null;
  session_count: number;
  restore_mode: "replace";
}

interface GryphonStatus {
  version: string;
  serviceId: string;
  state: string;
  connected: boolean;
  commandPrefix: string | null;
  bot: { id: string; alias: string; username?: string; state: string } | null;
  binding: { linkedAt: string } | null;
}

interface GryphonBot {
  id: string;
  alias: string;
  username?: string;
  state: string;
  selected: boolean;
}

interface NeptuneAvailability { installed: boolean | null; linked: boolean | null; state: "linked" | "unlinking" | "unlinked" | "unavailable" | "authorization_failed"; version?: string | null }
interface MonthlyReportStatus {
  enabled: boolean;
  template_path: string;
  reports: Array<{ month: string; state: string; attempts: number; last_error: string; mastermind_path: string | null; delivered_at: string | null }>;
}

const FALLBACK_ZONES = ["UTC", "Europe/Istanbul", "Europe/Moscow", "Europe/London", "America/New_York", "America/Los_Angeles", "Asia/Dubai", "Asia/Tokyo"];

function timezoneOptions(): string[] {
  try {
    const supported = (Intl as unknown as { supportedValuesOf: (key: string) => string[] }).supportedValuesOf("timeZone");
    return ["UTC", ...supported.filter((value) => value !== "UTC")];
  } catch {
    return FALLBACK_ZONES;
  }
}

function validOrder(value?: SettingsKey[]): SettingsKey[] {
  return value?.length === DEFAULT_ORDER.length && new Set(value).size === DEFAULT_ORDER.length ? value : DEFAULT_ORDER;
}

function accentReadable(value: string): boolean {
  if (!/^#[0-9a-fA-F]{6}$/.test(value)) return false;
  const rgb = [1, 3, 5].map((index) => Number.parseInt(value.slice(index, index + 2), 16) / 255);
  const luminance = rgb.map((channel) => channel <= .04045 ? channel / 12.92 : ((channel + .055) / 1.055) ** 2.4)
    .reduce((sum, channel, index) => sum + channel * [0.2126, 0.7152, 0.0722][index], 0);
  return (luminance + .05) / .05 >= 4.5;
}

function validKernelOrigin(value: string): boolean {
  try {
    const url = new URL(value);
    return url.protocol === "https:" && url.username === "" && url.password === "" && url.pathname === "/" && !url.search && !url.hash;
  } catch {
    return false;
  }
}

export default function Settings({ settings, onSettingsChanged }: { settings?: SettingsValues; onSettingsChanged: (settings: SettingsValues) => void }) {
  const [data, setData] = useState<SettingsResponse | null>(null);
  const [values, setValues] = useState<SettingsValues | null>(settings ?? null);
  const [updates, setUpdates] = useState<UpdateStatus | null>(null);
  const [accentDraft, setAccentDraft] = useState(settings?.theme_accent ?? "#00a8ff");
  const [accessOpen, setAccessOpen] = useState(false);
  const [accessKeys, setAccessKeys] = useState({ current: "", next: "", repeat: "" });
  const [accessPending, setAccessPending] = useState(false);
  const [kernelUrl, setKernelUrl] = useState("");
  const [kernelUrlPending, setKernelUrlPending] = useState(false);
  const [kernelTokenOpen, setKernelTokenOpen] = useState(false);
  const [kernelTokens, setKernelTokens] = useState({ next: "", repeat: "" });
  const [kernelTokenPending, setKernelTokenPending] = useState(false);
  const [restoreOpen, setRestoreOpen] = useState(false);
  const [restoreFile, setRestoreFile] = useState<File | null>(null);
  const [inspection, setInspection] = useState<BackupInspection | null>(null);
  const [restorePending, setRestorePending] = useState(false);
  const [restoreError, setRestoreError] = useState("");
  const [neptune, setNeptune] = useState<NeptuneAvailability | null>(null);
  const [monthlyStatus, setMonthlyStatus] = useState<MonthlyReportStatus | null>(null);
  const [monthlyTemplate, setMonthlyTemplate] = useState<{ path: string; sha256: string; anchor: string } | null>(null);
  const [monthlyPending, setMonthlyPending] = useState(false);
  const [neptuneUnlinking, setNeptuneUnlinking] = useState(false);
  const [gryphon, setGryphon] = useState<GryphonStatus | null>(null);
  const [gryphonBots, setGryphonBots] = useState<GryphonBot[]>([]);
  const [gryphonBotId, setGryphonBotId] = useState("");
  const [gryphonConnectionOpen, setGryphonConnectionOpen] = useState(false);
  const [gryphonPending, setGryphonPending] = useState(false);
  const [gryphonError, setGryphonError] = useState("");
  const [dragged, setDragged] = useState<SettingsKey | null>(null);
  const [drop, setDrop] = useState<{ key: SettingsKey; after: boolean } | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const { notify } = useNotices();
  const zones = useMemo(timezoneOptions, []);

  const load = useCallback(async () => {
    try {
      const [settingsResult, status] = await Promise.all([
        api<SettingsResponse>("/api/settings"),
        api<UpdateStatus>("/api/updates/status"),
      ]);
      setData(settingsResult);
      setValues(settingsResult.values);
      setAccentDraft(settingsResult.values.theme_accent);
      setKernelUrl(settingsResult.runtime.kernel_url ?? "");
      setUpdates(status);
      onSettingsChanged(settingsResult.values);
    } catch (error) {
      notify("error", error instanceof Error ? error.message : "Settings could not be loaded.");
    }
  }, [notify, onSettingsChanged]);

  useEffect(() => { void load(); }, [load]);
  const loadNeptune = useCallback(async () => {
    try { setNeptune(await api<NeptuneAvailability>("/api/neptune/availability")); }
    catch { setNeptune(previous => ({ installed: null, linked: null, ...previous, state: "unavailable" })); }
  }, []);
  useEffect(() => { void loadNeptune(); const timer = setInterval(() => void loadNeptune(), 15000); return () => clearInterval(timer); }, [loadNeptune]);
  const loadMonthly = useCallback(async () => {
    try { setMonthlyStatus(await api<MonthlyReportStatus>("/api/monthly-reports/status")); }
    catch { /* Settings remain editable while the status endpoint is unavailable. */ }
  }, []);
  useEffect(() => { void loadMonthly(); const timer = setInterval(() => void loadMonthly(), 30000); return () => clearInterval(timer); }, [loadMonthly]);
  const checkMonthlyTemplate = async () => {
    if (!values?.monthly_report_template_path) return;
    setMonthlyPending(true);
    try {
      const result = await api<{ path: string; sha256: string; anchor: string }>(`/api/monthly-reports/template?path=${encodeURIComponent(values.monthly_report_template_path)}`);
      setMonthlyTemplate(result);
      notify("success", `Template found; report branch: ${result.anchor}.`);
    } catch (error) {
      setMonthlyTemplate(null);
      notify("error", error instanceof Error ? error.message : "Mastermind template could not be checked.");
    } finally { setMonthlyPending(false); }
  };
  const runMonthlyReport = async () => {
    setMonthlyPending(true);
    try {
      setMonthlyStatus(await api<MonthlyReportStatus>("/api/monthly-reports/run", { method: "POST" }));
      notify("success", "Pending monthly reports were checked for delivery.");
    } catch (error) {
      notify("error", error instanceof Error ? error.message : "Monthly report could not be started.");
    } finally { setMonthlyPending(false); }
  };
  const loadGryphon = useCallback(async () => {
    try {
      const status = await api<GryphonStatus>("/api/gryphon/status");
      setGryphon(status); setGryphonError("");
    } catch (error) { setGryphonError(error instanceof Error ? error.message : "Unavailable"); }
  }, []);
  useEffect(() => { void loadGryphon(); const timer = setInterval(() => void loadGryphon(), 5000); return () => clearInterval(timer); }, [loadGryphon]);
  const commit = async (patch: Partial<SettingsValues>, message = "Setting saved.") => {
    if (!values) return;
    const previous = values;
    const optimistic = { ...values, ...patch };
    setValues(optimistic);
    onSettingsChanged(optimistic);
    try {
      const result = await api<{ values: SettingsValues }>("/api/settings", { method: "PATCH", body: JSON.stringify(patch) });
      setValues(result.values);
      setData((current) => current ? { ...current, values: result.values } : current);
      onSettingsChanged(result.values);
      notify("success", message);
    } catch (error) {
      setValues(previous);
      onSettingsChanged(previous);
      notify("error", error instanceof Error ? error.message : "Setting could not be saved.");
    }
  };

  const changeAccessKey = async (event: FormEvent) => {
    event.preventDefault();
    if (accessPending) return;
    if (accessKeys.next !== accessKeys.repeat) return notify("error", "New Access Key entries do not match.");
    setAccessPending(true);
    try {
      await api("/api/security/access-key", {
        method: "POST",
        body: JSON.stringify({ current_access_key: accessKeys.current, new_access_key: accessKeys.next, confirm_access_key: accessKeys.repeat }),
      });
      setAccessKeys({ current: "", next: "", repeat: "" });
      setAccessOpen(false);
      notify("success", "Access Key changed. Other sessions were revoked.");
    } catch (error) {
      notify("error", error instanceof Error ? error.message : "Access Key could not be changed.");
    } finally {
      setAccessPending(false);
    }
  };

  const commitKernelUrl = async () => {
    if (!data) return;
    const normalized = kernelUrl.trim().replace(/\/$/, "");
    const confirmed = data.runtime.kernel_url ?? "";
    if (normalized === confirmed) return;
    if (!validKernelOrigin(normalized)) {
      setKernelUrl(confirmed);
      return notify("error", "Kernel URL must be an HTTPS origin.");
    }
    if (!data.runtime.kernel_configured) return;
    setKernelUrlPending(true);
    try {
      const result = await api<{ kernel_url: string; kernel_reachable: boolean }>("/api/security/kernel-url", {
        method: "PUT", body: JSON.stringify({ kernel_url: normalized }),
      });
      setKernelUrl(result.kernel_url);
      setData({ ...data, runtime: { ...data.runtime, ...result } });
      notify("success", "Kernel URL validated and activated.");
    } catch (error) {
      setKernelUrl(confirmed);
      notify("error", error instanceof Error ? error.message : "Kernel URL could not be activated.");
    } finally {
      setKernelUrlPending(false);
    }
  };

  const rotateKernelToken = async (event: FormEvent) => {
    event.preventDefault();
    if (kernelTokenPending) return;
    if (!validKernelOrigin(kernelUrl)) return notify("error", "Enter a valid HTTPS Kernel URL first.");
    if (kernelTokens.next !== kernelTokens.repeat) return notify("error", "Kernel token entries do not match.");
    setKernelTokenPending(true);
    try {
      await api("/api/security/kernel-token", {
        method: "POST",
        body: JSON.stringify({ kernel_url: kernelUrl, new_token: kernelTokens.next, confirm_token: kernelTokens.repeat }),
      });
      setKernelTokens({ next: "", repeat: "" });
      setKernelTokenOpen(false);
      notify("success", "Kernel token validated and rotated.");
      await load();
    } catch (error) {
      notify("error", error instanceof Error ? error.message : "Kernel token could not be rotated.");
    } finally {
      setKernelTokenPending(false);
    }
  };

  const inspectRestore = async (file: File) => {
    setRestoreFile(file);
    setInspection(null);
    setRestoreError("");
    const form = new FormData();
    form.append("file", file);
    try {
      setInspection(await api<BackupInspection>("/api/backup/inspect", { method: "POST", body: form }));
    } catch (error) {
      setRestoreError(error instanceof Error ? error.message : "Backup validation failed.");
    }
  };

  const restore = async () => {
    if (!restoreFile || !inspection) return;
    setRestorePending(true);
    const form = new FormData();
    form.append("file", restoreFile);
    try {
      const result = await api<{ restored_sessions: number; reauthenticate?: boolean }>("/api/backup/restore", { method: "POST", body: form });
      notify("success", `Snapshot restored: ${result.restored_sessions} sessions. Sign in with the restored Access Key.`);
      closeRestore();
      if (result.reauthenticate) { window.location.assign("/"); return; }
      await load();
    } catch (error) {
      setRestoreError(error instanceof Error ? error.message : "Snapshot could not be restored.");
    } finally {
      setRestorePending(false);
    }
  };

  const closeRestore = () => {
    setRestoreOpen(false); setRestoreFile(null); setInspection(null); setRestoreError("");
    if (fileRef.current) fileRef.current.value = "";
  };


  const openGryphonConnection = async () => {
    setGryphonPending(true);
    try {
      const result = await api<{ bots: GryphonBot[] }>("/api/gryphon/bots");
      setGryphonBots(result.bots);
      setGryphonBotId(gryphon?.bot?.id ?? "");
      setGryphonConnectionOpen(true);
    } catch (error) { notify("error", error instanceof Error ? error.message : "Gryphon bot list could not be loaded."); }
    finally { setGryphonPending(false); }
  };

  const initializeAgent = () => openAgentInitialization({
    component: "Neptune", service: "chronos",
    description: "Initialize this service connection through the local Updater. Existing shared agents are reused.",
    codeLabel: "One-time setup code", profile: "Required pipeline: recovery ZIP archive.",
    initialize: input => api<InitializationJob>("/api/neptune/initialize", { method: "POST", body: JSON.stringify(input) }),
    observe: id => api<InitializationJob>("/api/updates/jobs/" + encodeURIComponent(id || "")),
    recover: async hint => {
      if (hint?.id) return api<InitializationJob>("/api/updates/jobs/" + encodeURIComponent(hint.id));
      const result = await api<{ jobs: (InitializationJob & { service?: string })[] }>("/api/update-flow/jobs");
      return result.jobs.find(job => job.service === "neptune-initialization" &&
        (hint?.request_id ? job.request_id === hint.request_id : !["COMPLETED", "FAILED"].includes(job.state)));
    },
    verify: async () => {
      const availability = await api<NeptuneAvailability>("/api/neptune/availability"); setNeptune(availability);
      return { ready: availability.state === "linked" && availability.linked === true,
        message: "Installation is not enough: the scoped archive pipeline must report a verified connection." };
    },
  });

  const unlinkNeptune = async () => {
    if (!(["linked", "unlinking"].includes(neptune?.state ?? "")) || !await confirmAgentAction({
      title: "Unlink Neptune agent", confirmLabel: "Unlink agent",
      message: "Automatic Chronos backups will stop. Saved archives remain in Saturn. Other services and the shared Neptune agent stay connected. Chronos will need a new setup code to link again.",
    })) return;
    setNeptuneUnlinking(true);
    try {
      const accepted = await api<{ id: string }>("/api/neptune/unlink", { method: "POST", body: "{}" });
      for (let attempt = 0; attempt < 600; attempt += 1) {
        const job = await api<{ state: string; message?: string }>(`/api/updates/jobs/${encodeURIComponent(accepted.id)}`);
        if (job.state === "COMPLETED") { await loadNeptune(); notify("success", "Chronos unlinked from Neptune. Automatic backups are off."); return; }
        if (job.state === "FAILED") throw new Error(job.message || "Neptune unlink failed");
        await new Promise(resolve => setTimeout(resolve, 1500));
      }
      throw new Error("Neptune is still finishing an accepted backup. Check its status before retrying.");
    } catch (error) { notify("error", error instanceof Error ? error.message : "Neptune unlink failed."); }
    finally { setNeptuneUnlinking(false); }
  };

  const connectGryphon = async (botId: string) => {
    if (!botId || (botId === gryphon?.bot?.id && gryphon.binding)) return;
    setGryphonPending(true);
    try {
      await api("/api/gryphon/connection", { method: "PUT", body: JSON.stringify({ botId }) });
      setGryphonBotId(botId); await loadGryphon(); notify("success", "Chronos function and paired Telegram account linked.");
    } catch (error) { notify("error", error instanceof Error ? error.message : "Chronos function could not be linked."); }
    finally { setGryphonPending(false); }
  };

  const disconnectGryphon = async () => {
    if (!await confirmAgentAction({ title: "Unlink service function", message: "Telegram commands and notifications for this service will stop, and its Telegram binding will be removed. Other services and the shared bot remain connected.", confirmLabel: "Unlink function" })) return;
    setGryphonPending(true);
    try {
      await api("/api/gryphon/connection", { method: "DELETE" });
      setGryphonBotId(""); await loadGryphon(); notify("success", "Chronos function unlinked from Gryphon.");
    } catch (error) { notify("error", error instanceof Error ? error.message : "Chronos function could not be unlinked."); }
    finally { setGryphonPending(false); }
  };

  if (!data || !values) return <LoadingBlock label="Loading Chronos settings..." />;

  const order = validOrder(values.settings_order);
  const move = (key: SettingsKey, direction: -1 | 1) => {
    const index = order.indexOf(key);
    const target = Math.max(0, Math.min(order.length - 1, index + direction));
    if (target === index) return;
    const next = [...order]; next.splice(index, 1); next.splice(target, 0, key);
    void commit({ settings_order: next }, "Settings section order saved.");
  };
  const dropSection = () => {
    if (!dragged || !drop || dragged === drop.key) return setDragged(null);
    const next = order.filter((key) => key !== dragged);
    next.splice(next.indexOf(drop.key) + (drop.after ? 1 : 0), 0, dragged);
    setDragged(null); setDrop(null);
    void commit({ settings_order: next }, "Settings section order saved.");
  };
  const cardProps = (key: SettingsKey, extraClass = "") => ({
    ordinal: order.indexOf(key) + 1,
    span: "4x" as const,
    reorderLabel: `${key} settings`,
    onDragStart: () => setDragged(key),
    onDragEnd: () => { setDragged(null); setDrop(null); },
    onDragOver: (event: React.DragEvent<HTMLElement>) => {
      event.preventDefault(); const rect = event.currentTarget.getBoundingClientRect();
      setDrop({ key, after: event.clientY > rect.top + rect.height / 2 });
    },
    onDrop: (event: React.DragEvent<HTMLElement>) => { event.preventDefault(); dropSection(); },
    onMove: (direction: -1 | 1) => move(key, direction),
    className: `${dragged === key ? "is-dragging" : ""} ${drop?.key === key ? (drop.after ? "drop-after" : "drop-before") : ""} ${extraClass}`,
  });

  const sections: Record<SettingsKey, React.ReactNode> = {
    appearance: <UniversalCard title="Appearance" {...cardProps("appearance", "settings-appearance-card")}>
      <div className="settings-groups">
        <section className="settings-group"><h3>Color correction</h3><p>Changes preview immediately and apply to both authenticated views and sign-in.</p>
          <div className="accent-row">
            <label className="swatch-control"><input type="color" value={/^#[0-9a-fA-F]{6}$/.test(accentDraft) ? accentDraft : values.theme_accent} onChange={(event) => { setAccentDraft(event.target.value); applyTheme(event.target.value); }} aria-label="Accent color" /></label>
            <input aria-label="Accent hex value" value={accentDraft} onChange={(event) => { const value = event.target.value; setAccentDraft(value); if (/^#[0-9a-fA-F]{6}$/.test(value)) applyTheme(value); }} />
            <button type="button" onClick={() => { setAccentDraft("#00a8ff"); applyTheme("#00a8ff"); }} data-smart-hover>Reset color</button>
            <button type="button" disabled={!accentReadable(accentDraft) || accentDraft.toLowerCase() === values.theme_accent.toLowerCase()} onClick={() => void commit({ theme_accent: accentDraft.toLowerCase() }, "Accent color applied.")} data-smart-hover>Apply color</button>
          </div>
          {!accentReadable(accentDraft) && <p className="inline-error">Use a valid #RRGGBB color with readable contrast on black.</p>}
        </section>
        <section className="settings-group"><h3>Left menu position</h3><p>Reveal the Sidebar from the edge or keep it fixed on wide screens.</p>
          <label className="toggle-control"><input type="checkbox" checked={values.sidebar_auto_hide} onChange={(event) => void commit({ sidebar_auto_hide: event.target.checked }, "Sidebar mode saved.")} /><span>Auto open and hide sidebar on mouse hover</span></label>
        </section>
      </div>
    </UniversalCard>,
    security: <UniversalCard title="Security" {...cardProps("security", "settings-security-card")}>
      <div className="settings-groups">
        <section className="settings-group"><h3>Changing Access Key</h3><p>Changing the Access Key revokes every other active browser session.</p><button type="button" className="wide-command" onClick={() => { setAccessKeys({ current: "", next: "", repeat: "" }); setAccessOpen(true); }} data-smart-hover>Change Access Key</button></section>
        <section className="settings-group"><h3>Connection with Kernel</h3>
          <div className="kernel-connection-controls">
            <label><span className="visually-hidden">Kernel URL</span><input type="url" aria-label="Kernel URL" placeholder="https://kernel.example.com" value={kernelUrl} disabled={kernelUrlPending || kernelTokenPending} onChange={(event) => setKernelUrl(event.target.value)} onBlur={() => void commitKernelUrl()} onKeyDown={(event) => { if (event.key === "Enter") event.currentTarget.blur(); }} /></label>
            <div className="kernel-row"><span>Kernel Core</span><span className={data.runtime.kernel_reachable ? "status-success" : "status-error"}>{data.runtime.kernel_reachable ? "Service reachable" : data.runtime.kernel_configured ? "Last check failed" : "Not configured"}</span><StatusSquare state={data.runtime.kernel_reachable ? "success" : "danger"} /></div>
          </div>
          {!data.runtime.kernel_configured && kernelUrl && <p className="form-hint">The URL will become authoritative together with the first validated token.</p>}
          <button type="button" className="wide-command" disabled={kernelUrlPending} onClick={() => { setKernelTokens({ next: "", repeat: "" }); setKernelTokenOpen(true); }} data-smart-hover>Rotate secure Kernel access token</button>
        </section>
      </div>
    </UniversalCard>,
    backup: <UniversalCard title="Backup" {...cardProps("backup", "settings-backup-card")}>
      <div className="settings-groups backup-content">
        <section className="settings-group"><h3>Manual snapshot</h3><p>Snapshots contain sessions, settings, Undo history and the Access Key verifier. Service tokens remain on the target machine. Restore signs out every session.</p><button type="button" className="settings-action" onClick={async () => { try { const name = await downloadFile("/api/backup/export"); notify("success", `${name} created and downloaded.`); } catch (error) { notify("error", error instanceof Error ? error.message : "Snapshot could not be created."); } }} data-smart-hover>Create and download snapshot</button></section>
        <section className="settings-group backup-neptune-group"><h3>Automatic backup to Saturn</h3><p>Neptune exports the same ZIP as the manual action and uploads it without changing its bytes.</p>
          <div className="service-status-row"><span>Local Neptune agent:</span><span>{!neptune ? "Checking" : neptune.state === "linked" ? "Linked" : neptune.state === "unlinking" ? "Unlinking" : neptune.state === "unlinked" ? "Not linked" : neptune.state === "authorization_failed" ? "Authorization failed" : neptune.linked ? "Unavailable · last known linked" : "Unavailable · installation unknown"}</span><StatusSquare state={neptune?.state === "linked" ? "success" : "danger"} /></div>
          <BackupPolicyPanel service="chronos" base="/api/neptune/policy" headers={policyHeaders} />
          {neptune?.state === "linked" || neptune?.linked === true ? <button type="button" className="settings-action backup-unlink-action" disabled={neptuneUnlinking || !["linked", "unlinking"].includes(neptune?.state ?? "")} onClick={() => void unlinkNeptune()}>{neptuneUnlinking ? "Unlinking Neptune…" : neptune?.state === "unlinking" ? "Retry Neptune unlink" : "Unlink Neptune agent"}</button>
            : <button type="button" className="settings-action backup-link-action" disabled={!neptune || neptune.state === "unavailable" && neptune.linked !== false} onClick={() => initializeAgent()}>{neptune?.state === "authorization_failed" ? "Repair Neptune connection" : "Link Neptune agent"}</button>}
          </section>
        <section className="settings-group"><h3>Restore snapshot</h3><p>Validation completes before replacement begins. A pre-restore transaction protects the current timeline.</p><button type="button" className="settings-action" onClick={() => setRestoreOpen(true)} data-smart-hover>Browse local snapshot archive</button></section>
      </div>
    </UniversalCard>,
    gryphon: <UniversalCard title="Gryphon Connection" {...cardProps("gryphon", "settings-bot-card")}>
      <div className="settings-groups bot-connection-groups">
        <section className="settings-group"><h3>Gryphon bot binding</h3>
          <p>Gryphon owns the Telegram connection, service receives only service-scoped commands.</p>
          <div className="bot-connection-status"><div className="service-status-row"><span>Local Gryphon agent:</span><span className={gryphon && !gryphonError ? "status-success" : "status-error"}>{gryphon ? "Reachability" : "Checking"}</span><StatusSquare state={gryphon && !gryphonError ? "success" : "danger"} /></div>
            <div className="service-status-row"><span>Applied connection:</span><span className={gryphon?.connected && gryphon.binding && !gryphonError ? "status-success" : "status-error"}>Reachability</span><StatusSquare state={gryphon?.connected && gryphon.binding && !gryphonError ? "success" : "danger"} /></div></div>
          {gryphonError && <p className="inline-error" role="alert">{gryphonError}</p>}
          <p className="bot-connection-selected">Applied connection: <strong>{gryphon?.connected ? gryphon.bot?.alias ?? "unknown" : "none"}</strong></p>
          <button type="button" className="settings-action bot-connection-action" disabled={!gryphon || Boolean(gryphonError) || gryphonPending} onClick={() => void openGryphonConnection()}>{gryphon?.connected ? "Change Gryphon function" : "Link Gryphon function"}</button>
        </section>
      </div>
    </UniversalCard>,
    updates: <UniversalCard title="Updates" {...cardProps("updates", "settings-updates-card")}>
      <div className="settings-groups updates-content"><div className="settings-group update-pipeline-group"><h3>Update pipeline</h3><p>Release discovery comes from Kernel Register; replacement and rollback are performed by the local Updater.</p><p>Current installed version: <strong className="accent-text">v{updates?.installed_version ?? data.runtime.version}</strong></p>
        <div className="service-status-row"><span>Local Updater agent:</span><span className={updates?.updater.available ? "status-success" : "status-error"}>{updates?.updater.available ? "Service Reachability" : "Service Unavailable"}</span><StatusSquare state={updates?.updater.available ? "success" : "danger"} /></div>
        <div className="service-status-row"><span>Kernel Register:</span><span className={data.runtime.register_revision ? "status-success" : "status-error"}>{data.runtime.register_revision ? "Service Reachability" : "Service Unavailable"}</span><StatusSquare state={data.runtime.register_revision ? "success" : "danger"} /></div>
        <button type="button" className="settings-action" onClick={() => openChronosUpdates()} data-smart-hover>Check for updates</button>
      </div></div>
    </UniversalCard>,
    logs: <UniversalCard title="Logs" {...cardProps("logs")}>
      <ServiceLogsPanel base="/api/logs" download="/api/logs/download" />
    </UniversalCard>,
    personalization: <UniversalCard title="Personalization" {...cardProps("personalization")}>
      <div className="settings-form-grid">
        <label><span>Profile name</span><input value={values.profile_name} maxLength={64} onChange={(event) => setValues({ ...values, profile_name: event.target.value })} onBlur={() => data.values.profile_name !== values.profile_name && void commit({ profile_name: values.profile_name })} /></label>
        <label><span>Timezone</span><select value={values.timezone} onChange={(event) => void commit({ timezone: event.target.value })}>{zones.map((zone) => <option key={zone} value={zone}>{zone}</option>)}</select></label>
        <label><span>Week starts on</span><select value={values.week_starts_on} onChange={(event) => void commit({ week_starts_on: Number(event.target.value) })}><option value={1}>Monday</option><option value={7}>Sunday</option></select></label>
        <label><span>Time format</span><select value={values.time_format} onChange={(event) => void commit({ time_format: event.target.value as "12h" | "24h" })}><option value="24h">24 hour</option><option value="12h">12 hour</option></select></label>
        <label><span>Date format</span><select value={values.date_format} onChange={(event) => void commit({ date_format: event.target.value as SettingsValues["date_format"] })}><option value="DD.MM.YYYY">DD.MM.YYYY</option><option value="YYYY-MM-DD">YYYY-MM-DD</option><option value="MM/DD/YYYY">MM/DD/YYYY</option></select></label>
        <label><span>Long timer reminder, minutes</span><input type="number" min={0} max={10080} value={values.reminder_minutes} onChange={(event) => setValues({ ...values, reminder_minutes: Number(event.target.value) })} onBlur={() => data.values.reminder_minutes !== values.reminder_minutes && void commit({ reminder_minutes: values.reminder_minutes })} /></label>
        <label><span>Daily summary time</span><input type="time" value={values.daily_summary_time} disabled={!values.daily_summary_enabled} onChange={(event) => setValues({ ...values, daily_summary_time: event.target.value })} onBlur={() => data.values.daily_summary_time !== values.daily_summary_time && void commit({ daily_summary_time: values.daily_summary_time })} /></label>
        <label className="toggle-control"><input type="checkbox" checked={values.daily_summary_enabled} onChange={(event) => void commit({ daily_summary_enabled: event.target.checked })} /><span>Send the daily balance through Gryphon</span></label>
      </div>
      <section className="settings-group monthly-report-settings">
        <h3>Monthly report to Mastermind</h3>
        <p>Chronos reads a Markdown template from Mastermind after the month closes. The template contains the @note link to the graph branch; each report becomes a separate note in the Vault root.</p>
        <label><span>Template path in Mastermind</span><input value={values.monthly_report_template_path} placeholder="root/templates/chronos_note.md" maxLength={240} onChange={(event) => { setValues({ ...values, monthly_report_template_path: event.target.value }); setMonthlyTemplate(null); }} /></label>
        <div className="form-actions"><button type="button" disabled={monthlyPending || !values.monthly_report_template_path} onClick={() => void checkMonthlyTemplate()}>Check template</button><button type="button" disabled={monthlyPending || data.values.monthly_report_template_path === values.monthly_report_template_path} onClick={() => void commit({ monthly_report_template_path: values.monthly_report_template_path })}>Save template path</button></div>
        {monthlyTemplate?.path === values.monthly_report_template_path && <p className="form-hint">Linked branch: {monthlyTemplate.anchor}</p>}
        <label className="toggle-control"><input type="checkbox" checked={values.monthly_report_enabled} disabled={monthlyPending || data.values.monthly_report_template_path !== values.monthly_report_template_path} onChange={(event) => void commit({ monthly_report_enabled: event.target.checked })} /><span>Send a report after each calendar month</span></label>
        {monthlyStatus?.reports[0] && <p className="form-hint">Latest: {monthlyStatus.reports[0].month} · {monthlyStatus.reports[0].state}{monthlyStatus.reports[0].mastermind_path ? ` · ${monthlyStatus.reports[0].mastermind_path}` : ""}{monthlyStatus.reports[0].last_error ? ` · ${monthlyStatus.reports[0].last_error}` : ""}</p>}
        <button type="button" disabled={monthlyPending || !values.monthly_report_enabled} onClick={() => void runMonthlyReport()}>Process or retry pending report</button>
      </section>
    </UniversalCard>,
  };

  return <>
    <div className="settings-stack">{order.map((key) => <div key={key}>{sections[key]}</div>)}</div>

    {accessOpen && <Overlay title="Security" className="security-access-overlay" onClose={() => { setAccessOpen(false); setAccessKeys({ current: "", next: "", repeat: "" }); }} dismissible={!accessPending}><form className="form-grid" onSubmit={changeAccessKey}><label><span>Current Access Key</span><input type="password" autoComplete="current-password" value={accessKeys.current} onChange={(event) => setAccessKeys({ ...accessKeys, current: event.target.value })} /></label><label><span>New Access Key</span><input type="password" autoComplete="new-password" value={accessKeys.next} onChange={(event) => setAccessKeys({ ...accessKeys, next: event.target.value })} /></label><label><span>Repeat New Access Key</span><input type="password" autoComplete="new-password" value={accessKeys.repeat} onChange={(event) => setAccessKeys({ ...accessKeys, repeat: event.target.value })} /></label><p className="form-hint">Applying a new key revokes every other operator session.</p><div className="form-actions"><SubmitButton pending={accessPending} label="Change Access Key" pendingLabel="Changing..." /></div></form></Overlay>}

    {kernelTokenOpen && <Overlay title="Rotate Kernel access token" onClose={() => { setKernelTokenOpen(false); setKernelTokens({ next: "", repeat: "" }); }} dismissible={!kernelTokens.next && !kernelTokens.repeat && !kernelTokenPending}><form className="form-grid" onSubmit={rotateKernelToken}><p className="form-hint">The replacement is write-only and will be tested against <strong>{kernelUrl}</strong> before the current connection changes.</p><label><span>New Kernel token</span><input type="password" minLength={24} autoComplete="new-password" value={kernelTokens.next} onChange={(event) => setKernelTokens({ ...kernelTokens, next: event.target.value })} /></label><label><span>Repeat new Kernel token</span><input type="password" minLength={24} autoComplete="new-password" value={kernelTokens.repeat} onChange={(event) => setKernelTokens({ ...kernelTokens, repeat: event.target.value })} /></label><div className="form-actions"><button type="button" disabled={kernelTokenPending} onClick={() => { setKernelTokenOpen(false); setKernelTokens({ next: "", repeat: "" }); }} data-smart-hover>Cancel</button><SubmitButton pending={kernelTokenPending} label="Validate and rotate" pendingLabel="Validating..." /></div></form></Overlay>}

    {gryphonConnectionOpen && <Overlay title="Gryphon Connection" className="gryphon-choice-overlay" onClose={() => setGryphonConnectionOpen(false)} dismissible={!gryphonPending}>
      <p className="gryphon-choice-intro">Select a connection already applied through Gryphon</p>
      <div className="gryphon-choice-layout"><div className="gryphon-choice-list">{gryphonBots.some((bot) => bot.state === "ready" || bot.id === gryphon?.bot?.id) ? gryphonBots.filter((bot) => bot.state === "ready" || bot.id === gryphon?.bot?.id).map((bot) => <button key={bot.id} type="button" className={`gryphon-choice${gryphonBotId === bot.id ? " is-selected" : ""}`} aria-pressed={gryphonBotId === bot.id} disabled={bot.state !== "ready" || gryphonPending} onClick={() => void connectGryphon(bot.id)}><span className="gryphon-choice-check" aria-hidden="true" />{bot.username ? `@${bot.username}` : bot.alias}</button>) : <p>No paired bots are available. Register and pair one with sudo updater tui.</p>}</div>
        {gryphon?.connected && gryphon.bot && <div className="gryphon-adapter-config"><strong>Active adapter config:</strong><span>Bot: {gryphon.bot.alias}</span><span>{gryphon.bot.username ? `Telegram: @${gryphon.bot.username}` : "Telegram account paired in Gryphon"}</span><span>Chronos function: active</span></div>}
      </div>
      {gryphon?.connected && <button type="button" className="gryphon-unlink-action" disabled={gryphonPending} onClick={() => void disconnectGryphon()}>Unlink all adapters</button>}
    </Overlay>}

    {restoreOpen && <Overlay title="Restore Chronos snapshot" onClose={closeRestore} dismissible={!restoreFile && !restorePending}><div className="restore-flow"><input ref={fileRef} className="visually-hidden" type="file" accept=".zip,application/zip" onChange={(event) => { const file = event.target.files?.[0]; if (file) void inspectRestore(file); }} /><button type="button" disabled={restorePending} onClick={() => fileRef.current?.click()} data-smart-hover>Select native archive</button>{restoreFile && <div className="archive-metadata"><span>File</span><strong>{restoreFile.name.replace(/[\\/\u0000-\u001f]/g, "_")}</strong><span>Size</span><strong>{(restoreFile.size / 1024).toFixed(1)} KiB</strong>{inspection && <><span>Schema</span><strong>{inspection.schema}</strong><span>Created</span><strong>{inspection.created_at ? localDate(inspection.created_at, values) : "Unknown"}</strong><span>Sessions</span><strong>{inspection.session_count}</strong><span>Mode</span><strong>Replace current Chronos state</strong></>}</div>}{restoreFile && !inspection && !restoreError && <p className="form-hint">Validating archive structure and checksum…</p>}{restoreError && <p className="inline-error" role="alert">{restoreError}</p>}<div className="form-actions"><button type="button" disabled={restorePending} onClick={closeRestore} data-smart-hover>Cancel</button><button type="button" className="danger-button" disabled={!inspection || restorePending} onClick={() => void restore()} data-smart-hover>{restorePending ? "Restoring..." : "Restore and replace"}</button></div></div></Overlay>}



  </>;
}
