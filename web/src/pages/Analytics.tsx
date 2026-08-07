import { useCallback, useEffect, useMemo, useState } from "react";

import { api } from "../api";
import { CATEGORY_LABELS, dateInput, duration } from "../format";
import type { Analytics as AnalyticsData, Category } from "../types";
import { EmptyState, LoadingBlock, useNotices } from "../ui";


type Preset = "today" | "week" | "month" | "30d" | "custom";


function datesFor(preset: Preset): { start: string; end: string } {
  const now = new Date();
  const end = dateInput(now);
  if (preset === "today") return { start: end, end };
  if (preset === "week") {
    const start = new Date(now);
    const day = start.getDay() || 7;
    start.setDate(start.getDate() - day + 1);
    return { start: dateInput(start), end };
  }
  if (preset === "month") {
    return { start: dateInput(new Date(now.getFullYear(), now.getMonth(), 1)), end };
  }
  const start = new Date(now);
  start.setDate(start.getDate() - 29);
  return { start: dateInput(start), end };
}


export default function Analytics() {
  const initial = datesFor("week");
  const [preset, setPreset] = useState<Preset>("week");
  const [start, setStart] = useState(initial.start);
  const [end, setEnd] = useState(initial.end);
  const [data, setData] = useState<AnalyticsData | null>(null);
  const [loading, setLoading] = useState(true);
  const { notify } = useNotices();

  const load = useCallback(async () => {
    if (!start || !end || start > end) return;
    setLoading(true);
    try {
      setData(await api<AnalyticsData>(`/api/analytics?start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}`));
    } catch (error) {
      notify("error", error instanceof Error ? error.message : "Analytics could not be loaded.");
    } finally {
      setLoading(false);
    }
  }, [end, notify, start]);

  useEffect(() => {
    void load();
  }, [load]);

  const maxDay = useMemo(
    () => Math.max(1, ...(data?.days.map((day) => day.total_seconds) ?? [1])),
    [data],
  );

  const strongest = useMemo(
    () => data?.categories.reduce((best, item) => (item.seconds > best.seconds ? item : best), data.categories[0]),
    [data],
  );

  const selectPreset = (value: Preset) => {
    setPreset(value);
    if (value !== "custom") {
      const dates = datesFor(value);
      setStart(dates.start);
      setEnd(dates.end);
    }
  };

  return (
    <div className="analytics-layout">
      <section className="workspace analytics-controls">
        <div className="period-presets" role="group" aria-label="Analytics period">
          {(["today", "week", "month", "30d"] as Preset[]).map((value) => (
            <button
              type="button"
              key={value}
              className={preset === value ? "is-selected" : ""}
              onClick={() => selectPreset(value)}
              data-smart-hover
            >
              {value === "30d" ? "Last 30 days" : value[0].toUpperCase() + value.slice(1)}
            </button>
          ))}
        </div>
        <div className="date-range">
          <label>
            <span>START</span>
            <input
              type="date"
              value={start}
              onChange={(event) => {
                setPreset("custom");
                setStart(event.target.value);
              }}
            />
          </label>
          <span>TO</span>
          <label>
            <span>END</span>
            <input
              type="date"
              value={end}
              min={start}
              onChange={(event) => {
                setPreset("custom");
                setEnd(event.target.value);
              }}
            />
          </label>
        </div>
      </section>

      {loading && !data ? (
        <LoadingBlock label="Calculating analytics..." />
      ) : data ? (
        <>
          <section className="workspace analytics-summary">
            <div className="summary-total">
              <span className="eyebrow">TRACKED TIME</span>
              <strong>{duration(data.total_seconds)}</strong>
              <span>{start} — {end}</span>
            </div>
            <div className="metric-grid">
              {data.categories.map((item) => (
                <article className="metric-panel" key={item.category}>
                  <span>{item.label}</span>
                  <strong>{item.percent.toFixed(2)}%</strong>
                  <span>{duration(item.seconds)}</span>
                  <div className="metric-line"><span style={{ width: `${item.percent}%` }} /></div>
                </article>
              ))}
            </div>
          </section>

          <section className="workspace daily-chart-workspace">
            <div className="workspace-heading">
              <div>
                <span className="eyebrow">DISTRIBUTION</span>
                <h2>Daily tracked time</h2>
              </div>
              {strongest && data.total_seconds > 0 && (
                <span className="analytics-insight">
                  Dominant: {strongest.label} / {strongest.percent.toFixed(2)}%
                </span>
              )}
            </div>
            {data.days.length ? (
              <div className="daily-chart" role="img" aria-label="Daily time distribution chart">
                {data.days.map((day) => (
                  <div className="day-column" key={day.date} title={`${day.date}: ${duration(day.total_seconds)}`}>
                    <div className="day-bar" style={{ height: `${Math.max(2, (day.total_seconds / maxDay) * 100)}%` }}>
                      {(Object.keys(CATEGORY_LABELS) as Category[]).map((category) => {
                        const seconds = day.categories[category] ?? 0;
                        return seconds ? (
                          <span
                            key={category}
                            className={`bar-${category}`}
                            style={{ height: `${(seconds / day.total_seconds) * 100}%` }}
                            title={`${CATEGORY_LABELS[category]}: ${duration(seconds)}`}
                          />
                        ) : null;
                      })}
                    </div>
                    <span>{day.date.slice(5)}</span>
                  </div>
                ))}
              </div>
            ) : (
              <EmptyState>No tracked sessions exist in this period.</EmptyState>
            )}
            <div className="chart-legend">
              {(Object.keys(CATEGORY_LABELS) as Category[]).map((category) => (
                <span key={category} className={`legend-${category}`}>{CATEGORY_LABELS[category]}</span>
              ))}
            </div>
          </section>
        </>
      ) : (
        <EmptyState>Select a valid analytics period.</EmptyState>
      )}
    </div>
  );
}

