import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { api } from "../api";
import { CATEGORY_DESCRIPTIONS, duration, liveSeconds, localDate } from "../format";
import type { Category, DashboardData, Session, SettingsValues } from "../types";
import { EmptyState, LoadingBlock, useNotices } from "../ui";


interface DashboardProps {
  settings?: SettingsValues;
  onOpenTimeline: () => void;
}


export default function Dashboard({ settings, onOpenTimeline }: DashboardProps) {
  const [data, setData] = useState<DashboardData | null>(null);
  const [pending, setPending] = useState<Category | "stop" | "undo" | null>(null);
  const [tick, setTick] = useState(0);
  const syncedAt = useRef(0);
  const { notify } = useNotices();

  const load = useCallback(async () => {
    try {
      const result = await api<DashboardData>("/api/dashboard");
      const receivedAt = performance.now();
      syncedAt.current = receivedAt;
      setTick(receivedAt);
      setData(result);
    } catch (error) {
      notify("error", error instanceof Error ? error.message : "Dashboard could not be loaded.");
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

  const activeElapsed = useMemo(() => {
    if (!data?.active) return 0;
    return liveSeconds(data.active.timer_elapsed_seconds, elapsedSinceSync);
  }, [data, elapsedSinceSync]);

  const liveToday = useMemo(() => {
    if (!data?.active) return data?.today ?? null;
    const increment = Math.floor(elapsedSinceSync / 1000);
    const totalSeconds = data.today.total_seconds + increment;
    return {
      ...data.today,
      total_seconds: totalSeconds,
      categories: data.today.categories.map((item) => {
        const seconds = item.seconds + (item.category === data.active?.category ? increment : 0);
        return {
          ...item,
          seconds,
          percent: totalSeconds ? Math.round((seconds * 10000) / totalSeconds) / 100 : 0,
        };
      }),
    };
  }, [data, elapsedSinceSync]);

  const press = async (category: Category) => {
    setPending(category);
    try {
      const result = await api<{ started: Session | null; stopped: Session | null }>("/api/timer/press", {
        method: "POST",
        body: JSON.stringify({ category }),
      });
      notify(
        "success",
        result.started
          ? `${result.started.label} timer is active.`
          : `${result.stopped?.label ?? "Active"} timer stopped.`,
      );
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

  if (!data) return <LoadingBlock />;

  return (
    <div className="dashboard-layout">
      <section className="workspace dashboard-primary">
        <div className="workspace-heading">
          <div>
            <span className="eyebrow">CURRENT STATE</span>
            <h2>{data.active ? data.active.label : "No active timer"}</h2>
          </div>
          <div className={`live-status ${data.active ? "is-live" : ""}`}>
            <span className="live-indicator" aria-hidden="true" />
            {data.active ? "TRACKING" : "IDLE"}
          </div>
        </div>
        <div className="active-clock" aria-live="polite">
          {data.active ? duration(activeElapsed, true) : "00h 00m 00s"}
        </div>
        <p className="active-description">
          {data.active
            ? CATEGORY_DESCRIPTIONS[data.active.category]
            : "Select the category that best describes what you are doing now."}
        </p>
        <div className="active-actions">
          <button type="button" onClick={stop} disabled={!data.active || pending !== null} data-smart-hover>
            {pending === "stop" ? "Stopping..." : "Stop timer"}
          </button>
          <button type="button" onClick={undo} disabled={pending !== null} data-smart-hover>
            {pending === "undo" ? "Undoing..." : "Undo last action"}
          </button>
        </div>
        <div className="category-grid" aria-label="Chronos categories">
          {data.categories.map(({ key, label }) => {
            const metric = liveToday?.categories.find((item) => item.category === key);
            const active = data.active?.category === key;
            return (
              <button
                type="button"
                key={key}
                className={`category-control ${active ? "is-active" : ""}`}
                disabled={pending !== null}
                onClick={() => void press(key)}
                data-smart-hover
              >
                <span className="category-index">{String(data.categories.findIndex((item) => item.key === key) + 1).padStart(2, "0")}</span>
                <strong>{label}</strong>
                <span>{CATEGORY_DESCRIPTIONS[key]}</span>
                <span className="category-total">
                  {pending === key ? "Applying..." : duration(metric?.seconds ?? 0)}
                </span>
              </button>
            );
          })}
        </div>
      </section>

      <section className="workspace today-workspace">
        <div className="workspace-heading">
          <div>
            <span className="eyebrow">TODAY</span>
            <h2>Time balance</h2>
          </div>
          <strong className="total-value">{duration(liveToday?.total_seconds ?? 0)}</strong>
        </div>
        <div className="balance-list">
          {(liveToday?.categories ?? []).map((item) => (
            <div className="balance-row" key={item.category}>
              <div className="balance-meta">
                <span>{item.label}</span>
                <span>{item.percent.toFixed(2)}%</span>
                <span>{duration(item.seconds)}</span>
              </div>
              <div className="balance-track" aria-label={`${item.label}: ${item.percent.toFixed(2)} percent`}>
                <span style={{ width: `${Math.min(100, item.percent)}%` }} />
              </div>
            </div>
          ))}
        </div>
      </section>

      <section className="workspace recent-workspace">
        <div className="workspace-heading">
          <div>
            <span className="eyebrow">RECENT</span>
            <h2>Session stream</h2>
          </div>
          <button type="button" onClick={onOpenTimeline} data-smart-hover>
            Open timeline
          </button>
        </div>
        {data.recent.length ? (
          <div className="session-compact-list">
            {data.recent.map((session) => (
              <div className="session-compact-row" key={session.id}>
                <span className="session-state">{session.active ? "LIVE" : session.source.toUpperCase()}</span>
                <strong>{session.label}</strong>
                <span>{session.public_id} / {session.note || "No note"}</span>
                <span>{duration(session.active ? liveSeconds(session.timer_elapsed_seconds, elapsedSinceSync) : session.duration_seconds)}</span>
                <time>{localDate(session.started_at, settings)}</time>
              </div>
            ))}
          </div>
        ) : (
          <EmptyState>No sessions have been recorded yet.</EmptyState>
        )}
      </section>
    </div>
  );
}
