import { type FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";

import { api, downloadFile } from "../api";
import { applyTheme, localDate } from "../format";
import type { AuditEvent, SettingsResponse, SettingsValues } from "../types";
import { ConfirmOverlay, EmptyState, LoadingBlock, Overlay, StatusSquare, SubmitButton, UniversalCard, useNotices } from "../ui";

type SettingsKey = SettingsValues["settings_order"][number];
const DEFAULT_ORDER: SettingsKey[] = ["appearance", "security", "backup", "updates", "logs", "personalization", "telegram"];

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
  const [updateOpen, setUpdateOpen] = useState(false);
  const [release, setRelease] = useState<ReleaseCheck | null>(null);
  const [updatePending, setUpdatePending] = useState(false);
  const [job, setJob] = useState<Record<string, unknown> | null>(null);
  const [jobId, setJobId] = useState("");
  const [linkCode, setLinkCode] = useState<{ code: string; expiresAt: string } | null>(null);
  const [clock, setClock] = useState(Date.now());
  const [unlinkOpen, setUnlinkOpen] = useState(false);
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
  useEffect(() => {
    const timer = window.setInterval(() => void loadLogs(true), 5_000);
    return () => window.clearInterval(timer);
  }, [loadLogs]);
  useEffect(() => {
    const timer = window.setInterval(() => setClock(Date.now()), 1_000);
    return () => window.clearInterval(timer);
  }, []);
  useEffect(() => {
    if (linkCode && Date.parse(linkCode.expiresAt) <= clock) setLinkCode(null);
  }, [clock, linkCode]);
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

  const createLinkCode = async () => {
    try {
      const result = await api<{ code: string; expires_at: string }>("/api/telegram/link-code", { method: "POST" });
      setLinkCode({ code: result.code, expiresAt: result.expires_at });
      notify("info", "One-time Telegram link code created.");
    } catch (error) {
      notify("error", error instanceof Error ? error.message : "Link code could not be created.");
    }
  };

  const unlinkTelegram = async () => {
    try {
      await api("/api/telegram/link", { method: "DELETE" });
      setLinkCode(null);
      setUnlinkOpen(false);
      notify("success", "Telegram account unlinked.");
      await load();
    } catch (error) {
      notify("error", error instanceof Error ? error.message : "Telegram could not be unlinked.");
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
  const cardProps = (key: SettingsKey) => ({
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
    className: `${dragged === key ? "is-dragging" : ""} ${drop?.key === key ? (drop.after ? "drop-after" : "drop-before") : ""}`,
  });

  const remainingSeconds = linkCode ? Math.max(0, Math.ceil((Date.parse(linkCode.expiresAt) - clock) / 1000)) : 0;
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
    backup: <UniversalCard title="Backup" {...cardProps("backup")}>
      <div className="settings-groups">
        <section className="settings-group"><h3>System snapshot</h3><p>Logical snapshots contain sessions, presentation and Telegram owner binding, but no Access Key or service tokens.</p><button type="button" className="settings-action" onClick={async () => { try { const name = await downloadFile("/api/backup/export"); notify("success", `${name} created and downloaded.`); } catch (error) { notify("error", error instanceof Error ? error.message : "Snapshot could not be created."); } }} data-smart-hover>Create and download snapshot</button></section>
        <section className="settings-group"><h3>Restore snapshot</h3><p>Validation completes before replacement begins. A pre-restore transaction protects the current timeline.</p><button type="button" className="settings-action" onClick={() => setRestoreOpen(true)} data-smart-hover>Browse local snapshot archive</button></section>
      </div>
    </UniversalCard>,
    updates: <UniversalCard title="Updates" {...cardProps("updates")}>
      <div className="settings-groups"><div className="settings-group"><h3>Update pipeline</h3><p>Release discovery comes from Kernel Register; replacement and rollback are performed by the local Updater.</p><p>Current installed version: <strong className="accent-text">{updates?.installed_version ?? data.runtime.version}</strong></p>
        <div className="service-status-row"><span>Local updater agent</span><span className={updates?.updater.available ? "status-success" : "status-error"}>{updates?.updater.available ? "Service reachable" : "Unavailable"}</span><StatusSquare state={updates?.updater.available ? "success" : "danger"} /></div>
        <div className="service-status-row"><span>Kernel Register</span><span className={data.runtime.register_revision ? "status-success" : "status-error"}>{data.runtime.register_revision ? "Service reachable" : "Unavailable"}</span><StatusSquare state={data.runtime.register_revision ? "success" : "danger"} /></div>
        <button type="button" className="settings-action" disabled={!data.runtime.repository_url} onClick={openUpdate} data-smart-hover>Check for updates</button>
        {!data.runtime.repository_url && <p className="form-hint">Release discovery is disabled because no approved repository is configured.</p>}
      </div></div>
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
        <label className="toggle-control"><input type="checkbox" checked={values.daily_summary_enabled} onChange={(event) => void commit({ daily_summary_enabled: event.target.checked })} /><span>Send the daily balance through Telegram</span></label>
      </div>
    </UniversalCard>,
    telegram: <UniversalCard title="Telegram" {...cardProps("telegram")}>
      <p className="section-description">The private bot accepts commands only from the linked owner account.</p>
      <div className="telegram-status-grid"><div><span>Configuration</span><strong>{data.telegram.configured ? "Available" : "Missing"}</strong></div><div><span>Receiver</span><strong>{data.telegram.running ? "Running" : "Stopped"}</strong></div><div><span>Owner</span><strong>{data.telegram.linked ? "Linked" : "Not linked"}</strong></div><div><span>Bot identity</span><strong>{data.telegram.username ? `@${data.telegram.username}` : "Unknown"}</strong></div></div>
      {data.telegram.last_error && <p className="inline-error">{data.telegram.last_error}</p>}
      {!data.telegram.linked ? <div className="link-block"><button type="button" disabled={!data.telegram.running} onClick={() => void createLinkCode()} data-smart-hover>Create link code</button>{linkCode && <div className="link-code"><span>Send this exact command to the bot</span><strong>/link {linkCode.code}</strong><span>Single use · expires in {Math.floor(remainingSeconds / 60)}:{String(remainingSeconds % 60).padStart(2, "0")}</span></div>}</div> : <button type="button" className="danger-button settings-action" onClick={() => setUnlinkOpen(true)} data-smart-hover>Unlink Telegram</button>}
    </UniversalCard>,
  };

  const accessDirty = Boolean(accessKeys.current || accessKeys.next || accessKeys.repeat);
  return <>
    <div className="settings-stack">{order.map((key) => <div key={key}>{sections[key]}</div>)}</div>

    {accessOpen && <Overlay title="Change Access Key" onClose={() => { setAccessOpen(false); setAccessKeys({ current: "", next: "", repeat: "" }); }} dismissible={!accessDirty && !accessPending}><form className="form-grid" onSubmit={changeAccessKey}><label><span>Current Access Key</span><input type="password" autoComplete="current-password" value={accessKeys.current} onChange={(event) => setAccessKeys({ ...accessKeys, current: event.target.value })} /></label><label><span>New Access Key</span><input type="password" minLength={12} autoComplete="new-password" value={accessKeys.next} onChange={(event) => setAccessKeys({ ...accessKeys, next: event.target.value })} /></label><label><span>Repeat new Access Key</span><input type="password" minLength={12} autoComplete="new-password" value={accessKeys.repeat} onChange={(event) => setAccessKeys({ ...accessKeys, repeat: event.target.value })} /></label><p className="form-hint">Other browser sessions will be revoked after the verifier changes.</p><div className="form-actions"><button type="button" disabled={accessPending} onClick={() => { setAccessOpen(false); setAccessKeys({ current: "", next: "", repeat: "" }); }} data-smart-hover>Cancel</button><SubmitButton pending={accessPending} label="Change Access Key" pendingLabel="Changing..." /></div></form></Overlay>}

    {kernelTokenOpen && <Overlay title="Rotate Kernel access token" onClose={() => { setKernelTokenOpen(false); setKernelTokens({ next: "", repeat: "" }); }} dismissible={!kernelTokens.next && !kernelTokens.repeat && !kernelTokenPending}><form className="form-grid" onSubmit={rotateKernelToken}><p className="form-hint">The replacement is write-only and will be tested against <strong>{kernelUrl}</strong> before the current connection changes.</p><label><span>New Kernel token</span><input type="password" minLength={24} autoComplete="new-password" value={kernelTokens.next} onChange={(event) => setKernelTokens({ ...kernelTokens, next: event.target.value })} /></label><label><span>Repeat new Kernel token</span><input type="password" minLength={24} autoComplete="new-password" value={kernelTokens.repeat} onChange={(event) => setKernelTokens({ ...kernelTokens, repeat: event.target.value })} /></label><div className="form-actions"><button type="button" disabled={kernelTokenPending} onClick={() => { setKernelTokenOpen(false); setKernelTokens({ next: "", repeat: "" }); }} data-smart-hover>Cancel</button><SubmitButton pending={kernelTokenPending} label="Validate and rotate" pendingLabel="Validating..." /></div></form></Overlay>}

    {restoreOpen && <Overlay title="Restore Chronos snapshot" onClose={closeRestore} dismissible={!restoreFile && !restorePending}><div className="restore-flow"><input ref={fileRef} className="visually-hidden" type="file" accept=".zip,application/zip" onChange={(event) => { const file = event.target.files?.[0]; if (file) void inspectRestore(file); }} /><button type="button" disabled={restorePending} onClick={() => fileRef.current?.click()} data-smart-hover>Select native archive</button>{restoreFile && <div className="archive-metadata"><span>File</span><strong>{restoreFile.name.replace(/[\\/\u0000-\u001f]/g, "_")}</strong><span>Size</span><strong>{(restoreFile.size / 1024).toFixed(1)} KiB</strong>{inspection && <><span>Schema</span><strong>{inspection.schema}</strong><span>Created</span><strong>{inspection.created_at ? localDate(inspection.created_at, values) : "Unknown"}</strong><span>Sessions</span><strong>{inspection.session_count}</strong><span>Mode</span><strong>Replace current Chronos state</strong></>}</div>}{restoreFile && !inspection && !restoreError && <p className="form-hint">Validating archive structure and checksum…</p>}{restoreError && <p className="inline-error" role="alert">{restoreError}</p>}<div className="form-actions"><button type="button" disabled={restorePending} onClick={closeRestore} data-smart-hover>Cancel</button><button type="button" className="danger-button" disabled={!inspection || restorePending} onClick={() => void restore()} data-smart-hover>{restorePending ? "Restoring..." : "Restore and replace"}</button></div></div></Overlay>}

    {updateOpen && <Overlay title="Chronos update discovery" onClose={() => setUpdateOpen(false)} dismissible={!updatePending}><div className="update-flow"><div className="service-status-row"><span>Installed version</span><strong>{updates?.installed_version ?? data.runtime.version}</strong></div><div className="service-status-row"><span>Approved registry</span><strong>{data.runtime.register_revision ?? "Offline / no last-known revision"}</strong></div><div className="service-status-row"><span>Local updater</span><strong>{updates?.updater.available ? "Available" : "Unavailable"}</strong></div>{updatePending && <p className="form-hint">Checking and verifying the approved release source…</p>}{release && <div className="release-result"><strong>{release.update_available ? `Verified release ${release.available_version} is available` : "Installed release is up to date"}</strong>{release.published_at && <span>Published {localDate(release.published_at, values)}</span>}{release.release_url && <a href={release.release_url} target="_blank" rel="noreferrer">Open release notes</a>}</div>}{job && <pre className="job-state">{JSON.stringify(job, null, 2)}</pre>}<div className="form-actions"><button type="button" disabled={updatePending} onClick={() => setUpdateOpen(false)} data-smart-hover>Close</button><button type="button" disabled={updatePending} onClick={() => void checkUpdate()} data-smart-hover>Check again</button>{release?.update_available && <button type="button" disabled={updatePending || !updates?.updater.available} onClick={() => void applyUpdate()} data-smart-hover>Update to {release.available_version}</button>}</div></div></Overlay>}

    {unlinkOpen && <ConfirmOverlay title="Unlink Telegram" description={<><p>Revoke the linked Telegram identity from this Chronos instance?</p><p>The bot remains installed, but commands will be denied until a new owner is linked.</p></>} confirmLabel="Unlink Telegram" pendingLabel="Unlinking..." onConfirm={unlinkTelegram} onClose={() => setUnlinkOpen(false)} />}
  </>;
}
