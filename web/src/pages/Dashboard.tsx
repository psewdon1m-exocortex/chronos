import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { api } from "../api";
import { bytes, CATEGORY_DESCRIPTIONS, duration, liveSeconds, localDate } from "../format";
import type { Category, DashboardData, Session, SettingsValues } from "../types";
import { EmptyState, LoadingBlock, StatusSquare, UniversalCard, useNotices } from "../ui";

type DashboardKey = SettingsValues["dashboard_order"][number];
const DEFAULT_ORDER: DashboardKey[] = ["cpu", "ram", "disk", "uptime", "current", "today", "recent"];

interface DashboardProps {
  settings?: SettingsValues;
  onSettingsChanged: (settings: SettingsValues) => void;
}

function validOrder(value?: DashboardKey[]): DashboardKey[] {
  return value?.length === DEFAULT_ORDER.length && new Set(value).size === DEFAULT_ORDER.length
    ? value
    : DEFAULT_ORDER;
}

function percent(value: number | null): string {
  return value === null ? "Unavailable" : `${value.toFixed(1)}%`;
}

export default function Dashboard({ settings, onSettingsChanged }: DashboardProps) {
  const [data, setData] = useState<DashboardData | null>(null);
  const [pending, setPending] = useState<Category | "stop" | "undo" | null>(null);
  const [tick, setTick] = useState(0);
  const [stale, setStale] = useState(false);
  const [dragged, setDragged] = useState<DashboardKey | null>(null);
  const [drop, setDrop] = useState<{ key: DashboardKey; after: boolean } | null>(null);
  const syncedAt = useRef(0);
  const loadedOnce = useRef(false);
  const { notify } = useNotices();
  const order = validOrder(settings?.dashboard_order);

  const load = useCallback(async () => {
    try {
      const result = await api<DashboardData>("/api/dashboard");
      const receivedAt = performance.now();
      syncedAt.current = receivedAt;
      setTick(receivedAt);
      setData(result);
      setStale(false);
      loadedOnce.current = true;
    } catch (error) {
      setStale(true);
      if (!loadedOnce.current) notify("error", error instanceof Error ? error.message : "Dashboard could not be loaded.");
    }
  }, [notify]);

  useEffect(() => {
    void load();
    const refresh = window.setInterval(() => void load(), 5_000);
    return () => window.clearInterval(refresh);
  }, [load]);

  useEffect(() => {
    const timer = window.setInterval(() => setTick(performance.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);

  const elapsedSinceSync = Math.max(0, tick - syncedAt.current);
  const activeElapsed = useMemo(
    () => data?.active ? liveSeconds(data.active.timer_elapsed_seconds, elapsedSinceSync) : 0,
    [data, elapsedSinceSync],
  );
  const liveToday = useMemo(() => {
    if (!data?.active) return data?.today ?? null;
    const increment = Math.floor(elapsedSinceSync / 1000);
    const totalSeconds = data.today.total_seconds + increment;
    return {
      ...data.today,
      total_seconds: totalSeconds,
      categories: data.today.categories.map((item) => {
        const seconds = item.seconds + (item.category === data.active?.category ? increment : 0);
        return { ...item, seconds, percent: totalSeconds ? Math.round((seconds * 10000) / totalSeconds) / 100 : 0 };
      }),
    };
  }, [data, elapsedSinceSync]);

  const press = async (category: Category) => {
    setPending(category);
    try {
      const result = await api<{ started: Session | null; stopped: Session | null }>("/api/timer/press", {
        method: "POST", body: JSON.stringify({ category }),
      });
      notify("success", result.started ? `${result.started.label} timer is active.` : `${result.stopped?.label ?? "Active"} timer stopped.`);
      await load();
    } catch (error) {
      notify("error", error instanceof Error ? error.message : "Timer action failed.");
    } finally {
      setPending(null);
    }
  };

  const stop = async () => {
    setPending("stop");
    try {
      const result = await api<{ stopped: Session | null }>("/api/timer/stop", { method: "POST" });
      notify("success", result.stopped ? `${result.stopped.label} timer stopped.` : "No timer was active.");
      await load();
    } catch (error) {
      notify("error", error instanceof Error ? error.message : "Timer could not be stopped.");
    } finally {
      setPending(null);
    }
  };

  const undo = async () => {
    setPending("undo");
    try {
      await api("/api/actions/undo", { method: "POST" });
      notify("success", "Last timer action undone.");
      await load();
    } catch (error) {
      notify("error", error instanceof Error ? error.message : "Nothing could be undone.");
    } finally {
      setPending(null);
    }
  };

  const saveOrder = async (next: DashboardKey[]) => {
    if (!settings) return;
    const previous = settings;
    onSettingsChanged({ ...settings, dashboard_order: next });
    try {
      const result = await api<{ values: SettingsValues }>("/api/settings", {
        method: "PATCH", body: JSON.stringify({ dashboard_order: next }),
      });
      onSettingsChanged(result.values);
      notify("success", "Dashboard order saved.");
    } catch (error) {
      onSettingsChanged(previous);
      notify("error", error instanceof Error ? error.message : "Dashboard order could not be saved.");
    }
  };

  const move = (key: DashboardKey, direction: -1 | 1) => {
    const index = order.indexOf(key);
    const destination = Math.max(0, Math.min(order.length - 1, index + direction));
    if (destination === index) return;
    const next = [...order];
    next.splice(index, 1);
    next.splice(destination, 0, key);
    void saveOrder(next);
  };

  const dropCard = () => {
    if (!dragged || !drop || dragged === drop.key) return setDragged(null);
    const next = order.filter((key) => key !== dragged);
    next.splice(next.indexOf(drop.key) + (drop.after ? 1 : 0), 0, dragged);
    setDragged(null);
    setDrop(null);
    void saveOrder(next);
  };

  if (!data) return <LoadingBlock />;

  const ordinal = (key: DashboardKey) => order.indexOf(key) + 1;
  const dragProps = (key: DashboardKey) => ({
    reorderLabel: key === "current" ? "Current State" : key === "today" ? "Today" : key,
    onDragStart: () => setDragged(key),
    onDragEnd: () => { setDragged(null); setDrop(null); },
    onDragOver: (event: React.DragEvent<HTMLElement>) => {
      event.preventDefault();
      const rect = event.currentTarget.getBoundingClientRect();
      setDrop({ key, after: event.clientY > rect.top + rect.height / 2 });
    },
    onDrop: (event: React.DragEvent<HTMLElement>) => { event.preventDefault(); dropCard(); },
    onMove: (direction: -1 | 1) => move(key, direction),
    className: `${dragged === key ? "is-dragging" : ""} ${drop?.key === key ? (drop.after ? "drop-after" : "drop-before") : ""}`,
  });

  const cards: Record<DashboardKey, React.ReactNode> = {
    cpu: (
      <UniversalCard ordinal={ordinal("cpu")} span="2x" {...dragProps("cpu")}>
        <div className="health-metric">
          <h2>CPU Usage</h2>
          <strong>{percent(data.telemetry.cpu.percent)} <span>— cores: {data.telemetry.cpu.logical_cores}</span></strong>
          <div className="progress-line" aria-label={`CPU usage ${percent(data.telemetry.cpu.percent)}`}><span style={{ width: `${data.telemetry.cpu.percent ?? 0}%` }} /></div>
        </div>
      </UniversalCard>
    ),
    ram: (
      <UniversalCard ordinal={ordinal("ram")} span="2x" {...dragProps("ram")}>
        <div className="health-metric">
          <h2>RAM Usage</h2>
          <strong>{percent(data.telemetry.ram.percent)} <span>— {bytes(data.telemetry.ram.used_bytes)} / {bytes(data.telemetry.ram.total_bytes)}</span></strong>
          <div className="progress-line" aria-label={`RAM usage ${percent(data.telemetry.ram.percent)}`}><span style={{ width: `${data.telemetry.ram.percent ?? 0}%` }} /></div>
        </div>
      </UniversalCard>
    ),
    disk: (
      <UniversalCard ordinal={ordinal("disk")} span="2x" {...dragProps("disk")}>
        <div className="health-metric">
          <h2>Disk Usage</h2>
          <strong>{percent(data.telemetry.disk.percent)} <span>— {bytes(data.telemetry.disk.used_bytes)} / {bytes(data.telemetry.disk.total_bytes)}</span></strong>
          <div className="progress-line" aria-label={`Disk usage ${percent(data.telemetry.disk.percent)}`}><span style={{ width: `${data.telemetry.disk.percent ?? 0}%` }} /></div>
        </div>
      </UniversalCard>
    ),
    uptime: (
      <UniversalCard ordinal={ordinal("uptime")} span="2x" {...dragProps("uptime")}>
        <div className="health-metric">
          <h2>Uptime</h2>
          <strong>Active: {duration(data.telemetry.uptime_seconds, true)}</strong>
        </div>
      </UniversalCard>
    ),
    current: (
      <UniversalCard ordinal={ordinal("current")} title="CURRENT STATE" span="4x" {...dragProps("current")}>
        <div className="current-state-heading">
          <div>
            <h3>{data.active ? data.active.label : "No active timer"}</h3>
            <p>{data.active ? CATEGORY_DESCRIPTIONS[data.active.category] : "Select the category that best describes what you are doing now."}</p>
          </div>
          {data.active && <div className="semantic-status is-success"><span>Tracking</span><StatusSquare state="success" /></div>}
        </div>
        <div className="active-clock" aria-live="polite">{data.active ? duration(activeElapsed, true) : "0h 0m 0s"}</div>
        <div className="active-actions">
          <button type="button" onClick={stop} disabled={!data.active || pending !== null} data-smart-hover>{pending === "stop" ? "Stopping..." : "Stop timer"}</button>
          <button type="button" onClick={undo} disabled={pending !== null} data-smart-hover>{pending === "undo" ? "Undoing..." : "Undo last action"}</button>
        </div>
        <div className="category-grid" aria-label="Chronos categories">
          {data.categories.map(({ key, label }, index) => {
            const metric = liveToday?.categories.find((item) => item.category === key);
            return (
              <button type="button" key={key} className={`category-control ${data.active?.category === key ? "is-active" : ""}`} disabled={pending !== null} onClick={() => void press(key)} data-smart-hover>
                <span className="category-index">{String(index + 1).padStart(2, "0")}</span>
                <strong>{label}</strong>
                <span>{CATEGORY_DESCRIPTIONS[key]}</span>
                <span className="category-total">{pending === key ? "Applying..." : duration(metric?.seconds ?? 0)}</span>
              </button>
            );
          })}
        </div>
      </UniversalCard>
    ),
    today: (
      <UniversalCard ordinal={ordinal("today")} title="TODAY" span="4x" {...dragProps("today")}>
        <div className="time-balance-heading"><h3>Time balance</h3><strong>{duration(liveToday?.total_seconds ?? 0)}</strong></div>
        <div className="balance-list">
          {(liveToday?.categories ?? []).map((item) => (
            <div className="balance-row" key={item.category}>
              <div className="balance-meta"><span>{item.label}</span><span>{item.percent.toFixed(2)}%</span><span>{duration(item.seconds)}</span></div>
              <div className="balance-track" aria-label={`${item.label}: ${item.percent.toFixed(2)} percent`}><span style={{ width: `${Math.min(100, item.percent)}%` }} /></div>
            </div>
          ))}
        </div>
      </UniversalCard>
    ),
    recent: (
      <UniversalCard ordinal={ordinal("recent")} title="RECENT" span="4x" {...dragProps("recent")}>
        <div className="recent-command"><h3>Session stream</h3></div>
        {data.recent.length ? <div className="session-compact-list">
          {data.recent.map((session) => (
            <div className="session-compact-row" key={session.id}>
              <span className="session-state">{session.active ? "LIVE" : session.source.toUpperCase()}</span>
              <strong>{session.label}</strong>
              <span>{session.public_id} / {session.note || "No note"}</span>
              <span>{duration(session.active ? liveSeconds(session.timer_elapsed_seconds, elapsedSinceSync) : session.duration_seconds)}</span>
              <time>{localDate(session.started_at, settings)}</time>
            </div>
          ))}
        </div> : <EmptyState>No sessions have been recorded yet.</EmptyState>}
      </UniversalCard>
    ),
  };

  return (
    <div className="dashboard-grid" aria-busy={stale}>
      {stale && <div className="stale-banner" role="status">Dashboard data is stale. Reconnecting…</div>}
      {order.map((key) => <div className={`dashboard-card-slot slot-${key}`} key={key}>{cards[key]}</div>)}
    </div>
  );
}
