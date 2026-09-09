import { useMemo, useState } from "react";

import { SearchField } from "../ui";


const SECTIONS = [
  {
    id: "principles",
    title: "Four-category model",
    content: (
      <>
        <p>Chronos describes personal time through four stable categories. They are intentionally fixed so long-term analytics remain comparable.</p>
        <table>
          <thead><tr><th>Category</th><th>Meaning</th></tr></thead>
          <tbody>
            <tr><td>Recovery</td><td>Sleep, rest and deliberate restoration.</td></tr>
            <tr><td>Accumulation</td><td>Learning, research and preparation that increases future capacity.</td></tr>
            <tr><td>Execution</td><td>Focused production, delivery and direct progress.</td></tr>
            <tr><td>Maintenance</td><td>Administration, care, communication and routine obligations.</td></tr>
          </tbody>
        </table>
        <div className="documentation-note">Choose the current category, not the desired one. Chronos measures reality rather than intention.</div>
      </>
    ),
    search: "categories recovery accumulation execution maintenance model",
  },
  {
    id: "tracking",
    title: "Tracking time",
    content: (
      <>
        <p>On Dashboard, activate a category to start its timer. Selecting another category closes the current session and starts the new one at the same timestamp. Selecting the active category stops it.</p>
        <h3>Undo</h3>
        <p><code>Undo last action</code> restores the state immediately before the most recent timer, edit, manual entry or deletion action. Only the latest action is retained for undo.</p>
        <h3>Overlaps</h3>
        <p>Chronos prevents overlapping sessions. Manual entries and edits must fit into an unoccupied interval.</p>
      </>
    ),
    search: "dashboard timer start stop switch undo overlap manual session",
  },
  {
    id: "timeline",
    title: "Timeline and corrections",
    content: (
      <>
        <p>Timeline lists every recorded session, including its source, duration and optional note. Search checks notes immediately; the category filter narrows the current list.</p>
        <p>Use <code>Add session</code> for time that was not tracked live. Edit corrects timestamps, category or note. Delete is soft and remains recoverable by the next Undo action.</p>
        <p>CSV export contains all non-deleted sessions in chronological order.</p>
      </>
    ),
    search: "timeline history search edit delete add manual csv export note",
  },
  {
    id: "analytics",
    title: "Analytics",
    content: (
      <>
        <p>Analytics supports today, the current week, the current month, the last 30 days, the current year and any custom date range up to 370 days.</p>
        <p>Sessions are clipped at period boundaries. A timer started before midnight contributes only the portion inside the selected day. The active timer is included up to the current moment.</p>
      </>
    ),
    search: "analytics percentages period date day week month chart active midnight",
  },
  {
    id: "telegram",
    title: "Telegram",
    content: (
      <>
        <p>Telegram transport and identity binding are owned by Gryphon. After the host CLI connects one or more bots, <strong>Link Chronos function</strong> in Settings selects one from that Gryphon-owned pool. Telegram-user authorization remains the separate <code>gryphon link issue chronos</code> CLI flow. The same card manages verified Gryphon Linux updates through Updater.</p>
        <h3>Commands</h3>
        <pre><code>{`/chronos status              active timer\n/chronos stats               today\n/chronos week                current week\n/chronos month               current month\n/chronos stop                stop active timer\n/chronos undo                undo last timer action\n/chronos retype              change the last completed session category\n/chronos backfill MINUTES    insert a completed session for the last N minutes`}</code></pre>
        <p>Retyping offers the four fixed category buttons. Backfill asks for whole minutes, then a category. It inserts a completed session, trims or removes overlapped entries, and preserves any active timer with the overlapped time deducted.</p>
        <p>Long-timer reminders and the daily summary follow the timezone and schedule configured in Settings.</p>
      </>
    ),
    search: "telegram link code commands status stats week month stop undo reminders summary",
  },
  {
    id: "data",
    title: "Data, backup and updates",
    content: (
      <>
        <p>PostgreSQL is the authoritative store for Chronos sessions, card order and navigation order. Gryphon independently owns Telegram bindings. A Chronos backup never includes the Access Key or service tokens.</p>
        <p>Kernel Register supplies the repository and public domain with a validated last-known-good cache. The local Updater creates another backup before replacing the immutable Chronos image and can restore it after rollback.</p>
      </>
    ),
    search: "postgresql backup restore kernel register updater release rollback security",
  },
];


export default function Documentation() {
  const [query, setQuery] = useState("");
  const visible = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    return normalized
      ? SECTIONS.filter((section) => `${section.title} ${section.search}`.toLowerCase().includes(normalized))
      : SECTIONS;
  }, [query]);

  return (
    <section className="documentation-workspace">
      <aside className="documentation-navigation">
        <div>
          <SearchField value={query} onChange={setQuery} placeholder="Search documentation" />
          <nav aria-label="Documentation sections">
            <span>CHRONOS GUIDE</span>
            {visible.map((section) => <a key={section.id} href={`#${section.id}`}>{section.title}</a>)}
          </nav>
        </div>
      </aside>
      <main className="documentation-article">
        <header>
          <span>EXOCORTEX / CHRONOS</span>
          <h1>Operator guide</h1>
          <p>How to measure, correct and interpret personal time without breaking the continuity of the record.</p>
        </header>
        {visible.length ? visible.map((section) => (
          <article id={section.id} key={section.id}>
            <h2>{section.title}</h2>
            {section.content}
          </article>
        )) : <div className="empty-state">No documentation section matches this search.</div>}
      </main>
    </section>
  );
}
