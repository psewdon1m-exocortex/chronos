import { type FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";

import { api, download } from "../api";
import { applyTheme, localDate } from "../format";
import type { AuditEvent, SettingsResponse, SettingsValues } from "../types";
import {
  ConfirmOverlay,
  EmptyState,
  LoadingBlock,
  SubmitButton,
  useNotices,
} from "../ui";


interface UpdateStatus {
  service: string;
  installed_version: string;
  repository_url: string | null;
  register_revision: string | null;
  updater: {
    installed: boolean;
    available: boolean;
    status?: string;
    version?: string;
    message?: string;
  };
}


interface ReleaseCheck {
  installed_version: string;
  available_version: string | null;
  update_available: boolean;
  release_url: string | null;
  published_at: string | null;
}


const FALLBACK_ZONES = [
  "UTC",
  "Europe/Istanbul",
  "Europe/Moscow",
  "Europe/London",
  "America/New_York",
  "America/Los_Angeles",
  "Asia/Dubai",
  "Asia/Tokyo",
];


function timezoneOptions(): string[] {
  try {
    const supported = (Intl as unknown as { supportedValuesOf: (key: string) => string[] }).supportedValuesOf("timeZone");
    return ["UTC", ...supported.filter((value) => value !== "UTC")];
  } catch {
    return FALLBACK_ZONES;
  }
}


export default function Settings({
  onSettingsChanged,
}: {
  onSettingsChanged: (settings: SettingsValues) => void;
}) {
  const [data, setData] = useState<SettingsResponse | null>(null);
  const [values, setValues] = useState<SettingsValues | null>(null);
  const [events, setEvents] = useState<AuditEvent[]>([]);
  const [updates, setUpdates] = useState<UpdateStatus | null>(null);
  const [release, setRelease] = useState<ReleaseCheck | null>(null);
  const [linkCode, setLinkCode] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [passwords, setPasswords] = useState({ current: "", next: "", repeat: "" });
  const [passwordPending, setPasswordPending] = useState(false);
  const [restoreFile, setRestoreFile] = useState<File | null>(null);
  const [updatePending, setUpdatePending] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const { notify } = useNotices();
  const zones = useMemo(timezoneOptions, []);

  const load = useCallback(async () => {
    try {
      const [settings, logs, status] = await Promise.all([
        api<SettingsResponse>("/api/settings"),
        api<{ events: AuditEvent[] }>("/api/logs?limit=100"),
        api<UpdateStatus>("/api/updates/status"),
      ]);
      setData(settings);
      setValues(settings.values);
      setEvents(logs.events);
      setUpdates(status);
    } catch (error) {
      notify("error", error instanceof Error ? error.message : "Settings could not be loaded.");
    }
  }, [notify]);

  useEffect(() => {
    void load();
  }, [load]);

  const save = async () => {
    if (!values || saving) return;
    setSaving(true);
    try {
      const result = await api<{ values: SettingsValues }>("/api/settings", {
        method: "PUT",
        body: JSON.stringify(values),
      });
      setValues(result.values);
      onSettingsChanged(result.values);
      notify("success", "Chronos personalization saved.");
      await load();
    } catch (error) {
      notify("error", error instanceof Error ? error.message : "Settings could not be saved.");
    } finally {
      setSaving(false);
    }
  };

  const resetAppearance = async () => {
    try {
      const result = await api<{ values: SettingsValues }>("/api/settings/reset-appearance", { method: "POST" });
      setValues(result.values);
      applyTheme(result.values.theme_dark, result.values.theme_light, result.values.theme_accent);
      onSettingsChanged(result.values);
      notify("success", "Appearance reset to the Exocortex defaults.");
    } catch (error) {
      notify("error", error instanceof Error ? error.message : "Appearance could not be reset.");
    }
  };

  const changePassword = async (event: FormEvent) => {
    event.preventDefault();
    if (passwordPending) return;
    if (passwords.next !== passwords.repeat) {
      notify("error", "New password and confirmation do not match.");
      return;
    }
    setPasswordPending(true);
    try {
      await api("/api/security/password", {
        method: "POST",
        body: JSON.stringify({ current_password: passwords.current, new_password: passwords.next }),
      });
      setPasswords({ current: "", next: "", repeat: "" });
      notify("success", "Operator password changed. Other sessions were revoked.");
    } catch (error) {
      notify("error", error instanceof Error ? error.message : "Password could not be changed.");
    } finally {
      setPasswordPending(false);
    }
  };

  const createLinkCode = async () => {
    try {
      const result = await api<{ code: string }>("/api/telegram/link-code", { method: "POST" });
      setLinkCode(result.code);
      notify("info", "One-time Telegram link code created for ten minutes.");
    } catch (error) {
      notify("error", error instanceof Error ? error.message : "Link code could not be created.");
    }
  };

  const unlinkTelegram = async () => {
    try {
      await api("/api/telegram/link", { method: "DELETE" });
      setLinkCode(null);
      notify("success", "Telegram account unlinked.");
      await load();
    } catch (error) {
      notify("error", error instanceof Error ? error.message : "Telegram could not be unlinked.");
    }
  };

  const restore = async () => {
    if (!restoreFile) return;
    const form = new FormData();
    form.append("file", restoreFile);
    try {
      const result = await api<{ restored_sessions: number }>("/api/backup/restore", {
        method: "POST",
        body: form,
      });
      notify("success", `Backup restored: ${result.restored_sessions} sessions.`);
      setRestoreFile(null);
      if (fileRef.current) fileRef.current.value = "";
      await load();
    } catch (error) {
      notify("error", error instanceof Error ? error.message : "Backup could not be restored.");
    }
  };

  const checkUpdate = async () => {
    setUpdatePending(true);
    try {
      const result = await api<ReleaseCheck>("/api/updates/check", { method: "POST" });
      setRelease(result);
      notify(
        "success",
        result.update_available
          ? `Chronos ${result.available_version} is available.`
          : "Chronos is on the latest stable release.",
      );
    } catch (error) {
      notify("error", error instanceof Error ? error.message : "Release check failed.");
    } finally {
      setUpdatePending(false);
    }
  };

  const applyUpdate = async () => {
    if (!release?.available_version) return;
    setUpdatePending(true);
    try {
      await api("/api/updates/apply", {
        method: "POST",
        body: JSON.stringify({ version: release.available_version }),
      });
      notify("info", `Update ${release.available_version} started. Chronos will restart after validation.`);
    } catch (error) {
      notify("error", error instanceof Error ? error.message : "Update could not be started.");
    } finally {
      setUpdatePending(false);
    }
  };

  if (!data || !values) return <LoadingBlock label="Loading Chronos settings..." />;

  const updateValue = <K extends keyof SettingsValues>(key: K, value: SettingsValues[K]) => {
    const next = { ...values, [key]: value };
    setValues(next);
    if (key === "theme_dark" || key === "theme_light" || key === "theme_accent") {
      applyTheme(next.theme_dark, next.theme_light, next.theme_accent);
    }
  };

  return (
    <div className="settings-stack">
      <section className="settings-section">
        <header>
          <h2>APPEARANCE</h2>
          <p>One dark, one light and one accent color define the complete Chronos interface.</p>
        </header>
        <div className="settings-content">
          <div className="settings-group">
            <div>
              <h3>Color correction</h3>
              <p>Changes preview immediately and apply to both authenticated views and sign-in.</p>
            </div>
            <div className="color-grid">
              {(["theme_dark", "theme_light", "theme_accent"] as const).map((key) => (
                <label key={key}>
                  <span>{key.replace("theme_", "").toUpperCase()}</span>
                  <span className="color-control">
                    <input
                      type="color"
                      value={values[key]}
                      onChange={(event) => updateValue(key, event.target.value)}
                      aria-label={`${key.replace("theme_", "")} color`}
                    />
                    <input
                      type="text"
                      value={values[key]}
                      pattern="#[0-9A-Fa-f]{6}"
                      onChange={(event) => updateValue(key, event.target.value)}
                    />
                  </span>
                </label>
              ))}
            </div>
            <button type="button" className="compact-button" onClick={() => void resetAppearance()} data-smart-hover>
              Reset colors
            </button>
          </div>
          <div className="settings-group settings-row">
            <div>
              <h3>Left menu</h3>
              <p>Reveal the Sidebar from the edge or keep it fixed on wide screens.</p>
            </div>
            <label className="toggle-control">
              <input
                type="checkbox"
                checked={values.sidebar_auto_hide}
                onChange={(event) => updateValue("sidebar_auto_hide", event.target.checked)}
              />
              <span>Auto open and hide sidebar on mouse hover</span>
            </label>
          </div>
        </div>
      </section>

      <section className="settings-section">
        <header>
          <h2>PERSONALIZATION</h2>
          <p>Chronos uses this context in web analytics, Telegram summaries and reminders.</p>
        </header>
        <div className="settings-content form-grid">
          <div className="form-columns">
            <label>
              <span>Profile name</span>
              <input value={values.profile_name} maxLength={64} onChange={(event) => updateValue("profile_name", event.target.value)} />
            </label>
            <label>
              <span>Timezone</span>
              <select value={values.timezone} onChange={(event) => updateValue("timezone", event.target.value)}>
                {zones.map((zone) => <option key={zone} value={zone}>{zone}</option>)}
              </select>
            </label>
          </div>
          <div className="form-columns three-columns">
            <label>
              <span>Week starts on</span>
              <select value={values.week_starts_on} onChange={(event) => updateValue("week_starts_on", Number(event.target.value))}>
                <option value={1}>Monday</option>
                <option value={7}>Sunday</option>
              </select>
            </label>
            <label>
              <span>Time format</span>
              <select value={values.time_format} onChange={(event) => updateValue("time_format", event.target.value as "12h" | "24h")}>
                <option value="24h">24 hour</option>
                <option value="12h">12 hour</option>
              </select>
            </label>
            <label>
              <span>Date format</span>
              <select value={values.date_format} onChange={(event) => updateValue("date_format", event.target.value as SettingsValues["date_format"])}>
                <option value="DD.MM.YYYY">DD.MM.YYYY</option>
                <option value="YYYY-MM-DD">YYYY-MM-DD</option>
                <option value="MM/DD/YYYY">MM/DD/YYYY</option>
              </select>
            </label>
          </div>
          <div className="form-columns">
            <label>
              <span>Long timer reminder, minutes</span>
              <input type="number" min={0} max={10080} value={values.reminder_minutes} onChange={(event) => updateValue("reminder_minutes", Number(event.target.value))} />
            </label>
            <label>
              <span>Daily summary time</span>
              <input type="time" value={values.daily_summary_time} onChange={(event) => updateValue("daily_summary_time", event.target.value)} disabled={!values.daily_summary_enabled} />
            </label>
          </div>
          <label className="toggle-control">
            <input type="checkbox" checked={values.daily_summary_enabled} onChange={(event) => updateValue("daily_summary_enabled", event.target.checked)} />
            <span>Send the daily balance through Telegram</span>
          </label>
        </div>
      </section>

      <section className="settings-section">
        <header>
          <h2>TELEGRAM</h2>
          <p>The private bot accepts commands only from the linked owner account.</p>
        </header>
        <div className="settings-content">
          <div className="status-grid">
            <div><span>CONFIGURATION</span><strong>{data.telegram.configured ? "AVAILABLE" : "MISSING"}</strong></div>
            <div><span>POLLING</span><strong>{data.telegram.running ? "RUNNING" : "STOPPED"}</strong></div>
            <div><span>OWNER</span><strong>{data.telegram.linked ? "LINKED" : "NOT LINKED"}</strong></div>
            <div><span>BOT</span><strong>{data.telegram.username ? `@${data.telegram.username}` : "UNKNOWN"}</strong></div>
          </div>
          {data.telegram.last_error && <p className="inline-error">{data.telegram.last_error}</p>}
          {!data.telegram.linked ? (
            <div className="link-block">
              <button type="button" onClick={() => void createLinkCode()} disabled={!data.telegram.running} data-smart-hover>
                Create link code
              </button>
              {linkCode && (
                <div className="link-code">
                  <span>SEND TO THE BOT</span>
                  <strong>/link {linkCode}</strong>
                  <span>The code expires in ten minutes and can be used once.</span>
                </div>
              )}
            </div>
          ) : (
            <button type="button" className="danger-button compact-button" onClick={() => void unlinkTelegram()} data-smart-hover>
              Unlink Telegram
            </button>
          )}
        </div>
      </section>

      <section className="settings-section">
        <header>
          <h2>SECURITY</h2>
          <p>Changing the operator password revokes every other active browser session.</p>
        </header>
        <div className="settings-content">
          <form className="form-grid nested-form" onSubmit={changePassword}>
            <label>
              <span>Current password</span>
              <input type="password" autoComplete="current-password" value={passwords.current} onChange={(event) => setPasswords({ ...passwords, current: event.target.value })} />
            </label>
            <div className="form-columns">
              <label>
                <span>New password</span>
                <input type="password" minLength={12} autoComplete="new-password" value={passwords.next} onChange={(event) => setPasswords({ ...passwords, next: event.target.value })} />
              </label>
              <label>
                <span>Repeat new password</span>
                <input type="password" minLength={12} autoComplete="new-password" value={passwords.repeat} onChange={(event) => setPasswords({ ...passwords, repeat: event.target.value })} />
              </label>
            </div>
            <SubmitButton pending={passwordPending} label="Change password" pendingLabel="Changing..." />
          </form>
        </div>
      </section>

      <section className="settings-section">
        <header>
          <h2>BACKUP</h2>
          <p>Logical snapshots contain sessions, personalization and the Telegram owner binding, but no passwords or service tokens.</p>
        </header>
        <div className="settings-content backup-actions">
          <div>
            <h3>System snapshot</h3>
            <button type="button" onClick={() => download("/api/backup/export")} data-smart-hover>Download backup ZIP</button>
          </div>
          <div>
            <h3>Restore</h3>
            <input ref={fileRef} type="file" accept=".zip,.json,application/zip,application/json" onChange={(event) => setRestoreFile(event.target.files?.[0] ?? null)} />
            <p className="form-hint">Restoring replaces the current Chronos timeline and settings. The external Telegram bot remains installed.</p>
          </div>
        </div>
      </section>

      <section className="settings-section">
        <header>
          <h2>UPDATES</h2>
          <p>Release discovery comes from Kernel Register; replacement and rollback are performed by the local Updater.</p>
        </header>
        <div className="settings-content">
          <div className="status-grid">
            <div><span>INSTALLED</span><strong>{updates?.installed_version ?? data.runtime.version}</strong></div>
            <div><span>UPDATER</span><strong>{updates?.updater.available ? "AVAILABLE" : "UNAVAILABLE"}</strong></div>
            <div><span>REGISTER</span><strong>{data.runtime.register_revision ?? "OFFLINE"}</strong></div>
            <div><span>REPOSITORY</span><strong>{data.runtime.repository_url ? "CONFIGURED" : "MISSING"}</strong></div>
          </div>
          {updates?.updater.message && <p className="form-hint">{updates.updater.message}</p>}
          {release && (
            <div className="release-result">
              <strong>{release.update_available ? `Release ${release.available_version} is available` : "Latest stable release installed"}</strong>
              {release.published_at && <span>Published {localDate(release.published_at, values)}</span>}
              {release.release_url && <a href={release.release_url} target="_blank" rel="noreferrer">Open release notes</a>}
            </div>
          )}
          <div className="form-actions left-actions">
            <button type="button" disabled={updatePending || !data.runtime.repository_url} onClick={() => void checkUpdate()} data-smart-hover>
              {updatePending ? "Checking..." : "Check for updates"}
            </button>
            {release?.update_available && (
              <button type="button" disabled={updatePending || !updates?.updater.available} onClick={() => void applyUpdate()} data-smart-hover>
                Update to {release.available_version}
              </button>
            )}
          </div>
        </div>
      </section>

      <section className="settings-section logger-section">
        <header>
          <h2>LOGGER</h2>
          <p>Compact action stream. Retention is limited by age and entry count; the strictest limit wins.</p>
          <button type="button" onClick={() => download("/api/logs/download")} data-smart-hover>Download Logs Zip</button>
        </header>
        <div className="settings-content">
          {events.length ? (
            <div className="event-stream">
              {events.map((event) => (
                <div className="event-row" key={event.id}>
                  <span className={`event-status status-${event.status}`}>{event.status.toUpperCase()}</span>
                  <strong>{event.action}</strong>
                  <span>{event.target || event.message || "Chronos"}</span>
                  <span>{event.actor}</span>
                  <time>{localDate(event.created_at, values)}</time>
                </div>
              ))}
            </div>
          ) : (
            <EmptyState>No audit events have been retained.</EmptyState>
          )}
        </div>
      </section>

      <div className="settings-save-bar">
        <span>Save appearance, personalization and notification preferences.</span>
        <button type="button" disabled={saving} onClick={() => void save()} data-smart-hover>
          {saving ? "Saving..." : "Save settings"}
        </button>
      </div>

      {restoreFile && (
        <ConfirmOverlay
          title="Restore Chronos backup"
          description={
            <>
              <p>Restore <strong>{restoreFile.name}</strong> and replace the complete local timeline?</p>
              <p>The current sessions and personalization will be replaced. Operator credentials remain unchanged. This action cannot be undone from the timer Undo command.</p>
            </>
          }
          confirmLabel="Restore backup"
          pendingLabel="Restoring..."
          onConfirm={restore}
          onClose={() => {
            setRestoreFile(null);
            if (fileRef.current) fileRef.current.value = "";
          }}
        />
      )}
    </div>
  );
}
