import { type FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";

import { api, downloadFile } from "../api";
import { applyTheme, localDate } from "../format";
import type { AuditEvent, SettingsResponse, SettingsValues } from "../types";
import { EmptyState, LoadingBlock, Overlay, StatusSquare, SubmitButton, UniversalCard, useNotices } from "../ui";

type SettingsKey = SettingsValues["settings_order"][number];
const DEFAULT_ORDER: SettingsKey[] = ["appearance", "security", "backup", "gryphon", "updates", "logs", "personalization"];

interface UpdateStatus {
  service: string;
  installed_version: string;
  repository_url: string | null;
  register_revision: string | null;
  updater: { installed: boolean; available: boolean; status?: string; version?: string; message?: string };
}

interface ReleaseCheck {
  installed_version: string;
  available_version: string | null;
  update_available: boolean;
  release_url: string | null;
  published_at: string | null;
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

interface NeptuneAvailability { installed: boolean; linked: boolean; state: "linked" | "unlinked" | "unavailable"; version?: string | null }
interface GryphonChallenge { code: string; expiresAt: string; command: string; botUsername?: string }

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
  const [events, setEvents] = useState<AuditEvent[]>([]);
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
  const [neptuneOpen, setNeptuneOpen] = useState(false);
  const [neptuneCode, setNeptuneCode] = useState("");
  const [neptunePending, setNeptunePending] = useState(false);
  const [gryphon, setGryphon] = useState<GryphonStatus | null>(null);
  const [gryphonBots, setGryphonBots] = useState<GryphonBot[]>([]);
  const [gryphonBotId, setGryphonBotId] = useState("");
  const [gryphonConnectionOpen, setGryphonConnectionOpen] = useState(false);
  const [gryphonPending, setGryphonPending] = useState(false);
  const [gryphonError, setGryphonError] = useState("");
  const [gryphonRelease, setGryphonRelease] = useState<ReleaseCheck | null>(null);
  const [gryphonChallenge, setGryphonChallenge] = useState<GryphonChallenge | null>(null);
  const [updateOpen, setUpdateOpen] = useState(false);
  const [release, setRelease] = useState<ReleaseCheck | null>(null);
  const [updatePending, setUpdatePending] = useState(false);
  const [job, setJob] = useState<Record<string, unknown> | null>(null);
  const [jobId, setJobId] = useState("");
  const [dragged, setDragged] = useState<SettingsKey | null>(null);
  const [drop, setDrop] = useState<{ key: SettingsKey; after: boolean } | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const cursor = useRef(0);
  const { notify } = useNotices();
  const zones = useMemo(timezoneOptions, []);

  const loadLogs = useCallback(async (incremental = false) => {
    if (document.visibilityState === "hidden") return;
    const suffix = incremental && cursor.current ? `&after_id=${cursor.current}` : "";
    const result = await api<{ events: AuditEvent[]; cursor: number }>(`/api/logs?limit=200${suffix}`);
    cursor.current = Math.max(cursor.current, result.cursor);
    setEvents((current) => {
      if (!incremental) return result.events;
      const known = new Set(current.map((event) => event.id));
      return [...result.events.filter((event) => !known.has(event.id)), ...current].slice(0, 200);
    });
  }, []);

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
      await loadLogs(false);
    } catch (error) {
      notify("error", error instanceof Error ? error.message : "Settings could not be loaded.");
    }
  }, [loadLogs, notify, onSettingsChanged]);

  useEffect(() => { void load(); }, [load]);
  const loadNeptune = useCallback(async () => {
    try { setNeptune(await api<NeptuneAvailability>("/api/neptune/availability")); }
    catch { setNeptune({ installed: false, linked: false, state: "unavailable" }); }
  }, []);
  useEffect(() => { void loadNeptune(); }, [loadNeptune]);
  const loadGryphon = useCallback(async () => {
    try {
      const status = await api<GryphonStatus>("/api/gryphon/status");
      setGryphon(status); setGryphonError("");
    } catch (error) { setGryphon(null); setGryphonError(error instanceof Error ? error.message : "Unavailable"); }
  }, []);
  useEffect(() => { void loadGryphon(); }, [loadGryphon]);
  useEffect(() => {
    const timer = window.setInterval(() => void loadLogs(true), 5_000);
    return () => window.clearInterval(timer);
  }, [loadLogs]);
  useEffect(() => {
    if (!jobId) return;
    const terminal = new Set(["COMPLETED", "FAILED", "ROLLED_BACK", "ROLLBACK_FAILED"]);
    const poll = async () => {
      try {
        const result = await api<Record<string, unknown>>(`/api/updates/jobs/${jobId}`);
        setJob(result);
        if (terminal.has(String(result.state ?? result.status ?? ""))) setJobId("");
      } catch {
        // A temporary disconnect is expected while Chronos is being replaced.
      }
    };
    void poll();
    const timer = window.setInterval(() => void poll(), 2_000);
    return () => window.clearInterval(timer);
  }, [jobId]);

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
      const result = await api<{ restored_sessions: number }>("/api/backup/restore", { method: "POST", body: form });
      notify("success", `Snapshot restored: ${result.restored_sessions} sessions.`);
      closeRestore();
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
      setGryphonBotId(result.bots.find((bot) => bot.state === "ready")?.id ?? "");
      setGryphonConnectionOpen(true);
    } catch (error) { notify("error", error instanceof Error ? error.message : "Gryphon bot list could not be loaded."); }
    finally { setGryphonPending(false); }
  };

  const initializeNeptune = async (event: FormEvent) => {
    event.preventDefault();
    if (!/^[A-Za-z0-9_-]{32}$/.test(neptuneCode)) { notify("error", "Enter the 32-character setup code from Saturn."); return; }
    setNeptunePending(true);
    try {
      await api("/api/neptune/initialize", { method: "POST", body: JSON.stringify({ enrollment_code: neptuneCode }) });
      setNeptuneCode(""); setNeptuneOpen(false);
      notify("success", "Neptune initialization started. Chronos may reconnect while the service is linked.");
    } catch (error) { notify("error", error instanceof Error ? error.message : "Neptune initialization could not be started."); }
    finally { setNeptunePending(false); }
  };

  const issueGryphonLink = async () => {
    setGryphonPending(true);
    try { setGryphonChallenge(await api<GryphonChallenge>("/api/gryphon/link-challenge", { method: "POST" })); }
    catch (error) { notify("error", error instanceof Error ? error.message : "Telegram link code could not be created."); }
    finally { setGryphonPending(false); }
  };

  const connectGryphon = async () => {
    if (!gryphonBotId) return;
    setGryphonPending(true);
    try {
      await api("/api/gryphon/connection", { method: "PUT", body: JSON.stringify({ botId: gryphonBotId }) });
      setGryphonConnectionOpen(false); await loadGryphon(); notify("success", "Chronos function linked to Gryphon.");
    } catch (error) { notify("error", error instanceof Error ? error.message : "Chronos function could not be linked."); }
    finally { setGryphonPending(false); }
  };

  const disconnectGryphon = async () => {
    setGryphonPending(true);
    try {
      await api("/api/gryphon/connection", { method: "DELETE" });
      await loadGryphon(); notify("success", "Chronos function unlinked from Gryphon.");
    } catch (error) { notify("error", error instanceof Error ? error.message : "Chronos function could not be unlinked."); }
    finally { setGryphonPending(false); }
  };

  const checkGryphon = async () => {
    setGryphonPending(true);
    try {
      const result = await api<ReleaseCheck>("/api/gryphon/update/check", { method: "POST" });
      setGryphonRelease(result);
      notify("success", result.update_available ? `Gryphon ${result.available_version} is available.` : "Gryphon is up to date.");
    }
    catch (error) { notify("error", error instanceof Error ? error.message : "Gryphon release check failed."); }
    finally { setGryphonPending(false); }
  };

  const installGryphon = async () => {
    const version = gryphonRelease?.available_version;
    if (!version) return;
    setGryphonPending(true);
    try {
      await api("/api/gryphon/update/install", { method: "POST", body: JSON.stringify({ version }) });
      setGryphonRelease(null); await loadGryphon(); notify("success", `Gryphon ${version} installed.`);
    } catch (error) { notify("error", error instanceof Error ? error.message : "Gryphon update failed."); }
    finally { setGryphonPending(false); }
  };

  const checkUpdate = async () => {
    setUpdatePending(true); setRelease(null);
    try {
      setRelease(await api<ReleaseCheck>("/api/updates/check", { method: "POST" }));
    } catch (error) {
      notify("error", error instanceof Error ? error.message : "Release verification failed.");
    } finally {
      setUpdatePending(false);
    }
  };

  const openUpdate = () => { setUpdateOpen(true); void checkUpdate(); };
  const applyUpdate = async () => {
    if (!release?.available_version) return;
    setUpdatePending(true);
    try {
      const result = await api<Record<string, unknown>>("/api/updates/apply", { method: "POST", body: JSON.stringify({ version: release.available_version }) });
      const id = String(result.job_id ?? result.id ?? "");
      setJob(result); setJobId(id);
      notify("info", `Update ${release.available_version} started.`);
    } catch (error) {
      notify("error", error instanceof Error ? error.message : "Update could not be started.");
    } finally {
      setUpdatePending(false);
    }
  };

  const refreshUpdaterVersion = async () => {
    try {
      const status = await api<UpdateStatus>("/api/updates/status");
      setUpdates(status);
      notify("info", "Updater version status refreshed.");
    } catch (error) {
      notify("error", error instanceof Error ? error.message : "Updater status could not be refreshed.");
    }
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
    appearance: <UniversalCard title="Appearance" {...cardProps("appearance")}>
      <div className="settings-groups">
        <section className="settings-group"><h3>Color correction</h3><p>Valid changes preview immediately. Only Apply makes the accent authoritative.</p>
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
    security: <UniversalCard title="Security" {...cardProps("security")}>
      <div className="settings-groups">
        <section className="settings-group"><h3>Changing Access Key</h3><p>Changing the Access Key revokes every other active browser session.</p><button type="button" className="wide-command" onClick={() => setAccessOpen(true)} data-smart-hover>Change Access Key</button></section>
        <section className="settings-group"><h3>Connection with Kernel</h3><p>Kernel identity and reachability are public status; its access token remains write-only.</p>
          <div className="kernel-connection-controls">
            <label><span className="visually-hidden">Kernel URL</span><input type="url" aria-label="Kernel URL" placeholder="https://kernel.example.com" value={kernelUrl} disabled={kernelUrlPending || kernelTokenPending} onChange={(event) => setKernelUrl(event.target.value)} onBlur={() => void commitKernelUrl()} onKeyDown={(event) => { if (event.key === "Enter") event.currentTarget.blur(); }} /></label>
            <div className="kernel-row"><span>Kernel Core</span><span className={data.runtime.kernel_reachable ? "status-success" : "status-error"}>{data.runtime.kernel_reachable ? "Service reachable" : data.runtime.kernel_configured ? "Last check failed" : "Not configured"}</span><StatusSquare state={data.runtime.kernel_reachable ? "success" : "danger"} /></div>
          </div>
          {!data.runtime.kernel_configured && kernelUrl && <p className="form-hint">The URL will become authoritative together with the first validated token.</p>}
          <button type="button" className="wide-command" disabled={!validKernelOrigin(kernelUrl) || kernelUrlPending} onClick={() => { setKernelTokens({ next: "", repeat: "" }); setKernelTokenOpen(true); }} data-smart-hover>Rotate secure Kernel access token</button>
        </section>
      </div>
    </UniversalCard>,
    backup: <UniversalCard title="Backup" {...cardProps("backup", "settings-backup-card")}>
      <div className="settings-groups backup-content">
        <section className="settings-group"><h3>System snapshot</h3><p>Logical snapshots contain sessions and presentation settings, but no Access Key or service tokens.</p><button type="button" className="settings-action" onClick={async () => { try { const name = await downloadFile("/api/backup/export"); notify("success", `${name} created and downloaded.`); } catch (error) { notify("error", error instanceof Error ? error.message : "Snapshot could not be created."); } }} data-smart-hover>Create and download snapshot</button></section>
        <section className="settings-group"><h3>Restore snapshot</h3><p>Validation completes before replacement begins. A pre-restore transaction protects the current timeline.</p><button type="button" className="settings-action" onClick={() => setRestoreOpen(true)} data-smart-hover>Browse local snapshot archive</button></section>
        <section className="settings-group backup-neptune-group"><h3>Automatic backup to Saturn</h3><p>Schedules, remote runs and Neptune fleet status are managed only from Saturn → Synchronization. Manual Chronos ZIP download and restore remain here.</p><div className="service-status-row"><span>Local Neptune agent:</span><span className={neptune?.linked ? "status-success" : "status-error"}>{neptune?.linked ? "Linked to Saturn" : neptune?.installed ? "Detected · not linked" : "Not installed"}</span><StatusSquare state={neptune?.linked ? "success" : "danger"} /></div>{neptune?.installed && !neptune.linked && <button type="button" className="settings-action" disabled={neptunePending || !updates?.updater.available} onClick={() => setNeptuneOpen(true)} data-smart-hover>Initialize Neptune</button>}</section>
      </div>
    </UniversalCard>,
    gryphon: <UniversalCard title="Bot connection" {...cardProps("gryphon", "settings-bot-card")}>
      <div className="settings-groups bot-connection-groups">
        <section className="settings-group"><h3>Gryphon bot binding</h3><p>Gryphon owns the Telegram connection, service receives only service-scoped commands.</p><div className="service-status-row bot-connection-status"><span>Local Gryphon agent:</span><span className={gryphon ? "status-success" : "status-error"}>{gryphon ? "Service Reachability" : "Service Unavailable"}</span><StatusSquare state={gryphon ? "success" : "danger"} /></div>{gryphon?.connected && gryphon.bot ? <p className="bot-connection-selected">Connected bot: <strong>{gryphon.bot.username ? `@${gryphon.bot.username}` : gryphon.bot.alias}</strong></p> : null}{gryphon?.connected && !gryphon.binding ? <button type="button" className="settings-action bot-connection-action" disabled={gryphonPending} onClick={() => void issueGryphonLink()} data-smart-hover>{gryphonPending ? "Creating…" : "Initialize bot"}</button> : null}<button type="button" className="settings-action bot-connection-action" disabled={!gryphon || gryphonPending} onClick={() => void (gryphon?.connected ? disconnectGryphon() : openGryphonConnection())} data-smart-hover>{gryphonPending ? "Working…" : gryphon?.connected ? "Unlink Chronos function" : "Link Chronos function"}</button>{gryphon?.binding ? <p className="bot-connection-selected">Telegram account linked.</p> : null}{!gryphon && gryphonError ? <p className="inline-error">{gryphonError}</p> : null}</section>
        <section className="settings-group"><h3>Gryphon version</h3><p>Current installed version: <strong>{gryphon?.version ?? "unavailable"}</strong>{gryphonRelease?.available_version ? ` · latest ${gryphonRelease.available_version}` : ""}</p><button type="button" className="settings-action" disabled={!gryphon || gryphonPending} onClick={() => void checkGryphon()} data-smart-hover>Check Gryphon for updates</button>{gryphonRelease?.update_available && <button type="button" className="settings-action" disabled={gryphonPending} onClick={() => void installGryphon()} data-smart-hover>{gryphonPending ? "Installing…" : `Install Gryphon ${gryphonRelease.available_version}`}</button>}</section>
      </div>
    </UniversalCard>,
    updates: <UniversalCard title="Updates" {...cardProps("updates", "settings-updates-card")}>
      <div className="settings-groups updates-content"><div className="settings-group update-pipeline-group"><h3>Update pipeline</h3><p>Release discovery comes from Kernel Register; replacement and rollback are performed by the local Updater.</p><p>Current installed version: <strong className="accent-text">v{updates?.installed_version ?? data.runtime.version}</strong></p>
        <div className="service-status-row"><span>Local Updater agent:</span><span className={updates?.updater.available ? "status-success" : "status-error"}>{updates?.updater.available ? "Service Reachability" : "Service Unavailable"}</span><StatusSquare state={updates?.updater.available ? "success" : "danger"} /></div>
        <div className="service-status-row"><span>Kernel Register:</span><span className={data.runtime.register_revision ? "status-success" : "status-error"}>{data.runtime.register_revision ? "Service Reachability" : "Service Unavailable"}</span><StatusSquare state={data.runtime.register_revision ? "success" : "danger"} /></div>
        <button type="button" className="settings-action" disabled={!data.runtime.repository_url} onClick={openUpdate} data-smart-hover>Check for updates</button>
      </div><div className="settings-group updater-version-group"><h3>Updater version</h3><p>Current installed version: {updates?.updater.version ?? "unavailable"}</p><button type="button" className="settings-action" disabled={updatePending} onClick={() => void refreshUpdaterVersion()} data-smart-hover>Check Updater for updates</button></div></div>
    </UniversalCard>,
    logs: <UniversalCard title="Logs" {...cardProps("logs")}>
      <div className="logs-command"><p>Compact bounded action stream. The newest 200 visible events are retained in this view.</p><button type="button" onClick={async () => { try { const name = await downloadFile("/api/logs/download"); notify("success", `${name} downloaded.`); } catch (error) { notify("error", error instanceof Error ? error.message : "Logs could not be downloaded."); } }} data-smart-hover>Download archived logs</button></div>
      {events.length ? <div className="event-stream" role="table" aria-label="Chronos audit events"><div className="event-header" role="row"><span>TYPE</span><span>BODY</span><span>TIME</span></div>{events.map((event) => <div className="event-row" role="row" key={event.id}><span className={`event-status status-${event.status}`}>/{event.status.toUpperCase()}</span><span><strong>{event.action}</strong> — {event.target || event.message || "Chronos"} · {event.actor}</span><time>{localDate(event.created_at, values)}</time></div>)}</div> : <EmptyState>No audit events have been retained.</EmptyState>}
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
    </UniversalCard>,
  };

  const accessDirty = Boolean(accessKeys.current || accessKeys.next || accessKeys.repeat);
  return <>
    <div className="settings-stack">{order.map((key) => <div key={key}>{sections[key]}</div>)}</div>

    {accessOpen && <Overlay title="Change Access Key" onClose={() => { setAccessOpen(false); setAccessKeys({ current: "", next: "", repeat: "" }); }} dismissible={!accessDirty && !accessPending}><form className="form-grid" onSubmit={changeAccessKey}><label><span>Current Access Key</span><input type="password" autoComplete="current-password" value={accessKeys.current} onChange={(event) => setAccessKeys({ ...accessKeys, current: event.target.value })} /></label><label><span>New Access Key</span><input type="password" minLength={12} autoComplete="new-password" value={accessKeys.next} onChange={(event) => setAccessKeys({ ...accessKeys, next: event.target.value })} /></label><label><span>Repeat new Access Key</span><input type="password" minLength={12} autoComplete="new-password" value={accessKeys.repeat} onChange={(event) => setAccessKeys({ ...accessKeys, repeat: event.target.value })} /></label><p className="form-hint">Other browser sessions will be revoked after the verifier changes.</p><div className="form-actions"><button type="button" disabled={accessPending} onClick={() => { setAccessOpen(false); setAccessKeys({ current: "", next: "", repeat: "" }); }} data-smart-hover>Cancel</button><SubmitButton pending={accessPending} label="Change Access Key" pendingLabel="Changing..." /></div></form></Overlay>}

    {kernelTokenOpen && <Overlay title="Rotate Kernel access token" onClose={() => { setKernelTokenOpen(false); setKernelTokens({ next: "", repeat: "" }); }} dismissible={!kernelTokens.next && !kernelTokens.repeat && !kernelTokenPending}><form className="form-grid" onSubmit={rotateKernelToken}><p className="form-hint">The replacement is write-only and will be tested against <strong>{kernelUrl}</strong> before the current connection changes.</p><label><span>New Kernel token</span><input type="password" minLength={24} autoComplete="new-password" value={kernelTokens.next} onChange={(event) => setKernelTokens({ ...kernelTokens, next: event.target.value })} /></label><label><span>Repeat new Kernel token</span><input type="password" minLength={24} autoComplete="new-password" value={kernelTokens.repeat} onChange={(event) => setKernelTokens({ ...kernelTokens, repeat: event.target.value })} /></label><div className="form-actions"><button type="button" disabled={kernelTokenPending} onClick={() => { setKernelTokenOpen(false); setKernelTokens({ next: "", repeat: "" }); }} data-smart-hover>Cancel</button><SubmitButton pending={kernelTokenPending} label="Validate and rotate" pendingLabel="Validating..." /></div></form></Overlay>}

    {gryphonConnectionOpen && <Overlay title="Link Chronos function" onClose={() => setGryphonConnectionOpen(false)} dismissible={!gryphonPending}><div className="bot-picker"><p className="form-hint">Select a Telegram bot already connected through the Gryphon CLI.</p><div className="bot-picker-list">{gryphonBots.length ? gryphonBots.map((bot) => <label key={bot.id} className={bot.state === "ready" ? "" : "is-disabled"}><input type="radio" name="chronos-gryphon-bot" value={bot.id} checked={gryphonBotId === bot.id} disabled={bot.state !== "ready" || gryphonPending} onChange={() => setGryphonBotId(bot.id)} /><span><strong>{bot.username ? `@${bot.username}` : bot.alias}</strong><small>{bot.alias} · {bot.state}</small></span></label>) : <p>No bots are connected. Add one with <code>gryphon bot connect</code>.</p>}</div><div className="form-actions"><button type="button" disabled={gryphonPending} onClick={() => setGryphonConnectionOpen(false)} data-smart-hover>Cancel</button><button type="button" disabled={!gryphonBotId || gryphonPending} onClick={() => void connectGryphon()} data-smart-hover>{gryphonPending ? "Linking…" : "Link function"}</button></div></div></Overlay>}

    {restoreOpen && <Overlay title="Restore Chronos snapshot" onClose={closeRestore} dismissible={!restoreFile && !restorePending}><div className="restore-flow"><input ref={fileRef} className="visually-hidden" type="file" accept=".zip,application/zip" onChange={(event) => { const file = event.target.files?.[0]; if (file) void inspectRestore(file); }} /><button type="button" disabled={restorePending} onClick={() => fileRef.current?.click()} data-smart-hover>Select native archive</button>{restoreFile && <div className="archive-metadata"><span>File</span><strong>{restoreFile.name.replace(/[\\/\u0000-\u001f]/g, "_")}</strong><span>Size</span><strong>{(restoreFile.size / 1024).toFixed(1)} KiB</strong>{inspection && <><span>Schema</span><strong>{inspection.schema}</strong><span>Created</span><strong>{inspection.created_at ? localDate(inspection.created_at, values) : "Unknown"}</strong><span>Sessions</span><strong>{inspection.session_count}</strong><span>Mode</span><strong>Replace current Chronos state</strong></>}</div>}{restoreFile && !inspection && !restoreError && <p className="form-hint">Validating archive structure and checksum…</p>}{restoreError && <p className="inline-error" role="alert">{restoreError}</p>}<div className="form-actions"><button type="button" disabled={restorePending} onClick={closeRestore} data-smart-hover>Cancel</button><button type="button" className="danger-button" disabled={!inspection || restorePending} onClick={() => void restore()} data-smart-hover>{restorePending ? "Restoring..." : "Restore and replace"}</button></div></div></Overlay>}

    {updateOpen && <Overlay title="Chronos update discovery" onClose={() => setUpdateOpen(false)} dismissible={!updatePending}><div className="update-flow"><div className="service-status-row"><span>Installed version</span><strong>{updates?.installed_version ?? data.runtime.version}</strong></div><div className="service-status-row"><span>Approved registry</span><strong>{data.runtime.register_revision ?? "Offline / no last-known revision"}</strong></div><div className="service-status-row"><span>Local updater</span><strong>{updates?.updater.available ? "Available" : "Unavailable"}</strong></div>{updatePending && <p className="form-hint">Checking and verifying the approved release source…</p>}{release && <div className="release-result"><strong>{release.update_available ? `Verified release ${release.available_version} is available` : "Installed release is up to date"}</strong>{release.published_at && <span>Published {localDate(release.published_at, values)}</span>}{release.release_url && <a href={release.release_url} target="_blank" rel="noreferrer">Open release notes</a>}</div>}{job && <pre className="job-state">{JSON.stringify(job, null, 2)}</pre>}<div className="form-actions"><button type="button" disabled={updatePending} onClick={() => setUpdateOpen(false)} data-smart-hover>Close</button><button type="button" disabled={updatePending} onClick={() => void checkUpdate()} data-smart-hover>Check again</button>{release?.update_available && <button type="button" disabled={updatePending || !updates?.updater.available} onClick={() => void applyUpdate()} data-smart-hover>Update to {release.available_version}</button>}</div></div></Overlay>}

    {neptuneOpen && <Overlay title="Initialize Neptune" onClose={() => !neptunePending && setNeptuneOpen(false)} dismissible={!neptuneCode && !neptunePending}><form className="form-grid" onSubmit={initializeNeptune}><p className="form-hint">Create a one-time Linux pipeline code in Saturn → Synchronization. It is sent directly to the local Updater and is never stored by Chronos.</p><label><span>Saturn setup code</span><input value={neptuneCode} minLength={32} maxLength={32} autoComplete="off" required onChange={(event) => setNeptuneCode(event.target.value.trim())} /></label><div className="form-actions"><button type="button" disabled={neptunePending} onClick={() => { setNeptuneOpen(false); setNeptuneCode(""); }} data-smart-hover>Cancel</button><SubmitButton pending={neptunePending} label="Initialize" pendingLabel="Starting…" /></div></form></Overlay>}

    {gryphonChallenge && <Overlay title="Link Telegram account" onClose={() => setGryphonChallenge(null)}><div className="form-grid"><p className="form-hint">Send this command to {gryphonChallenge.botUsername ? `@${gryphonChallenge.botUsername}` : "the connected bot"}. It can be used once and expires {localDate(gryphonChallenge.expiresAt, values)}.</p><div className="one-time-code"><strong>{gryphonChallenge.command}</strong></div><div className="form-actions"><button type="button" onClick={() => void navigator.clipboard.writeText(gryphonChallenge.command).then(() => notify("success", "Command copied."))} data-smart-hover>Copy command</button><button type="button" onClick={() => setGryphonChallenge(null)} data-smart-hover>Done</button></div></div></Overlay>}
  </>;
}
