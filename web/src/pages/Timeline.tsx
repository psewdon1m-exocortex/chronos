import { type FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";

import { api, download } from "../api";
import {
  CATEGORY_LABELS,
  duration,
  inputDateTime,
  liveSeconds,
  localDate,
  localDateKey,
  zonedDateTimeToIso,
} from "../format";
import type { Category, Session, SettingsValues } from "../types";
import {
  ConfirmOverlay,
  EmptyState,
  LoadingBlock,
  Overlay,
  SearchField,
  SubmitButton,
  useNotices,
} from "../ui";


const CATEGORIES = Object.keys(CATEGORY_LABELS) as Category[];


interface EditorState {
  session?: Session;
  category: Category;
  startedAt: string;
  stoppedAt: string;
  note: string;
}


function defaultEditor(timeZone?: string): EditorState {
  const end = new Date();
  const start = new Date(end.getTime() - 60 * 60 * 1000);
  return {
    category: "execution",
    startedAt: inputDateTime(start.toISOString(), timeZone),
    stoppedAt: inputDateTime(end.toISOString(), timeZone),
    note: "",
  };
}


function sessionEditor(session: Session, timeZone?: string): EditorState {
  return {
    session,
    category: session.category,
    startedAt: inputDateTime(session.started_at, timeZone),
    stoppedAt: session.stopped_at ? inputDateTime(session.stopped_at, timeZone) : "",
    note: session.note,
  };
}


export default function Timeline({ settings }: { settings?: SettingsValues }) {
  const [sessions, setSessions] = useState<Session[] | null>(null);
  const [total, setTotal] = useState(0);
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState<Category | "all">("all");
  const [editor, setEditor] = useState<EditorState | null>(null);
  const [deleting, setDeleting] = useState<Session | null>(null);
  const [pending, setPending] = useState(false);
  const [tick, setTick] = useState(0);
  const syncedAt = useRef(0);
  const { notify } = useNotices();

  const load = useCallback(async () => {
    const params = new URLSearchParams({ limit: "250", q: query.trim() });
    if (category !== "all") params.set("category", category);
    try {
      const result = await api<{ items: Session[]; total: number }>(`/api/sessions?${params}`);
      const receivedAt = performance.now();
      syncedAt.current = receivedAt;
      setTick(receivedAt);
      setSessions(result.items);
      setTotal(result.total);
    } catch (error) {
      notify("error", error instanceof Error ? error.message : "Timeline could not be loaded.");
    }
  }, [category, notify, query]);

  useEffect(() => {
    const delay = window.setTimeout(() => void load(), 150);
    const refresh = window.setInterval(() => void load(), 60_000);
    return () => {
      window.clearTimeout(delay);
      window.clearInterval(refresh);
    };
  }, [load]);

  useEffect(() => {
    const timer = window.setInterval(() => setTick(performance.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);

  const elapsedSinceSync = Math.max(0, tick - syncedAt.current);
  const sessionDuration = (session: Session): number =>
    session.active
      ? liveSeconds(session.duration_seconds, elapsedSinceSync)
      : session.duration_seconds;

  const grouped = useMemo(() => {
    const result = new Map<string, Session[]>();
    for (const session of sessions ?? []) {
      const key = localDateKey(session.started_at, settings?.timezone);
      result.set(key, [...(result.get(key) ?? []), session]);
    }
    return [...result.entries()];
  }, [sessions, settings?.timezone]);

  const save = async (event: FormEvent) => {
    event.preventDefault();
    if (!editor || pending) return;
    if (!editor.startedAt || (!editor.session?.active && !editor.stoppedAt)) {
      notify("error", "Start and end are required for a completed session.");
      return;
    }
    const payload = {
      category: editor.category,
      started_at: zonedDateTimeToIso(editor.startedAt, settings?.timezone),
      stopped_at: editor.stoppedAt
        ? zonedDateTimeToIso(editor.stoppedAt, settings?.timezone)
        : null,
      note: editor.note.trim(),
    };
    if (payload.stopped_at && Date.parse(payload.stopped_at) <= Date.parse(payload.started_at)) {
      notify("error", "Session end must be later than its start.");
      return;
    }
    setPending(true);
    try {
      if (editor.session) {
        await api(`/api/sessions/${editor.session.id}`, {
          method: "PUT",
          body: JSON.stringify(payload),
        });
        notify("success", "Session updated.");
      } else {
        await api("/api/sessions", {
          method: "POST",
          body: JSON.stringify({ ...payload, stopped_at: payload.stopped_at! }),
        });
        notify("success", "Manual session created.");
      }
      setEditor(null);
      await load();
    } catch (error) {
      notify("error", error instanceof Error ? error.message : "Session could not be saved.");
    } finally {
      setPending(false);
    }
  };

  const remove = async () => {
    if (!deleting) return;
    try {
      await api(`/api/sessions/${deleting.id}`, { method: "DELETE" });
      notify("success", `${deleting.label} session deleted. You can undo it from Dashboard.`);
      setDeleting(null);
      await load();
    } catch (error) {
      notify("error", error instanceof Error ? error.message : "Session could not be deleted.");
    }
  };

  return (
    <section className="workspace timeline-workspace">
      <div className="toolbar timeline-toolbar">
        <SearchField value={query} onChange={setQuery} placeholder="Search session notes" />
        <label className="compact-field">
          <span>CATEGORY</span>
          <select value={category} onChange={(event) => setCategory(event.target.value as Category | "all")}>
            <option value="all">All categories</option>
            {CATEGORIES.map((key) => (
              <option key={key} value={key}>{CATEGORY_LABELS[key]}</option>
            ))}
          </select>
        </label>
        <span className="result-count">{total} sessions</span>
        <button type="button" onClick={() => download("/api/export.csv")} data-smart-hover>
          Export CSV
        </button>
        <button type="button" onClick={() => setEditor(defaultEditor(settings?.timezone))} data-smart-hover>
          Add session
        </button>
      </div>

      {sessions === null ? (
        <LoadingBlock label="Loading timeline..." />
      ) : grouped.length ? (
        <div className="timeline-groups">
          {grouped.map(([day, items]) => (
            <section className="timeline-day" key={day}>
              <header>
                <h2>{day}</h2>
                <span>{duration(items.reduce((sum, item) => sum + sessionDuration(item), 0))}</span>
              </header>
              <div className="timeline-list">
                {items.map((session) => (
                  <article className={`timeline-entry ${session.active ? "is-active" : ""}`} key={session.id}>
                    <span className="timeline-category">
                      <span>{session.label}</span>
                      <small>{session.public_id}</small>
                    </span>
                    <div className="timeline-copy">
                      <strong>{session.note || "Untitled session"}</strong>
                      <span>
                        {localDate(session.started_at, settings)}
                        {session.stopped_at ? ` — ${localDate(session.stopped_at, settings)}` : " — Active"}
                      </span>
                    </div>
                    <span className="timeline-source">{session.source.toUpperCase()}</span>
                    <strong className="timeline-duration">{duration(sessionDuration(session), session.active)}</strong>
                    <div className="row-actions">
                      <button type="button" onClick={() => setEditor(sessionEditor(session, settings?.timezone))} data-smart-hover>
                        Edit
                      </button>
                      <button type="button" onClick={() => setDeleting(session)} data-smart-hover>
                        Delete
                      </button>
                    </div>
                  </article>
                ))}
              </div>
            </section>
          ))}
        </div>
      ) : (
        <EmptyState>
          {query || category !== "all" ? "No sessions match the current filter." : "No sessions recorded yet."}
        </EmptyState>
      )}

      {editor && (
        <Overlay title={editor.session ? "Edit session" : "Add manual session"} onClose={() => !pending && setEditor(null)}>
          <form className="form-grid" onSubmit={save}>
            <label>
              <span>Category</span>
              <select
                value={editor.category}
                onChange={(event) => setEditor({ ...editor, category: event.target.value as Category })}
              >
                {CATEGORIES.map((key) => (
                  <option key={key} value={key}>{CATEGORY_LABELS[key]}</option>
                ))}
              </select>
            </label>
            <div className="form-columns">
              <label>
                <span>Start</span>
                <input
                  type="datetime-local"
                  step={1}
                  required
                  value={editor.startedAt}
                  onChange={(event) => setEditor({ ...editor, startedAt: event.target.value })}
                />
              </label>
              <label>
                <span>End {editor.session?.active ? "(leave empty to keep active)" : ""}</span>
                <input
                  type="datetime-local"
                  step={1}
                  required={!editor.session?.active}
                  value={editor.stoppedAt}
                  onChange={(event) => setEditor({ ...editor, stoppedAt: event.target.value })}
                />
              </label>
            </div>
            <label>
              <span>Note</span>
              <textarea
                maxLength={500}
                rows={4}
                value={editor.note}
                onChange={(event) => setEditor({ ...editor, note: event.target.value })}
                placeholder="What happened during this session?"
              />
            </label>
            <p className="form-hint">Chronos rejects entries that overlap existing sessions.</p>
            <div className="form-actions">
              <button type="button" onClick={() => setEditor(null)} disabled={pending} data-smart-hover>
                Cancel
              </button>
              <SubmitButton pending={pending} label="Save session" pendingLabel="Saving..." />
            </div>
          </form>
        </Overlay>
      )}

      {deleting && (
        <ConfirmOverlay
          title="Delete session"
          description={
            <>
              <p>
                Delete the <strong>{deleting.label}</strong> session from {localDate(deleting.started_at, settings)}?
              </p>
              <p>The record will be removed locally from Chronos. It can be restored once with Undo.</p>
            </>
          }
          confirmLabel="Delete session"
          pendingLabel="Deleting..."
          onConfirm={remove}
          onClose={() => setDeleting(null)}
        />
      )}
    </section>
  );
}
