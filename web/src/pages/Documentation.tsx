import { isValidElement, useMemo, useRef, useState, type ReactNode } from "react";

type DocumentationGroup = "Get Started" | "Operate" | "Maintain";

interface DocumentationArticle {
  id: string;
  group: DocumentationGroup;
  title: string;
  summary: string;
  keywords: string;
  content: ReactNode;
}

export const DOCUMENTATION_ARTICLES: DocumentationArticle[] = [
  {
    id: "introduction",
    group: "Get Started",
    title: "Introduction",
    summary: "What Chronos records, what it deliberately leaves out and how to read its interface.",
    keywords: "overview chronos guide operator interface time record",
    content: (
      <>
        <p>Chronos is the time layer of Exocortex. It records what kind of activity is happening, preserves a correct timeline and turns that history into comparable analytics.</p>
        <h2>Core workflow</h2>
        <ol>
          <li>Start one of the four fixed activity categories on Dashboard or through Telegram.</li>
          <li>Use Timeline to inspect and correct the resulting sessions.</li>
          <li>Use Analytics to compare category balance and recorded-time coverage.</li>
          <li>Use Settings for appearance, access, backups, Gryphon and updates.</li>
        </ol>
        <div className="documentation-note"><strong>One timeline, one active timer.</strong> Chronos never runs two sessions at once and never guesses how unrecorded time was spent.</div>
      </>
    ),
  },
  {
    id: "categories",
    group: "Get Started",
    title: "Four-category model",
    summary: "A stable vocabulary that keeps long-term time data comparable.",
    keywords: "category recovery accumulation execution maintenance model meaning",
    content: (
      <>
        <p>The categories are intentionally fixed. Rename-free categories make a week from today comparable with a year from now.</p>
        <table>
          <thead><tr><th>Category</th><th>Use it for</th></tr></thead>
          <tbody>
            <tr><td>Recovery</td><td>Sleep, rest and deliberate restoration.</td></tr>
            <tr><td>Accumulation</td><td>Learning, research and preparation that increase future capacity.</td></tr>
            <tr><td>Execution</td><td>Focused production, delivery and direct progress.</td></tr>
            <tr><td>Maintenance</td><td>Administration, care, communication and routine obligations.</td></tr>
          </tbody>
        </table>
        <h2>Choosing a category</h2>
        <p>Choose the category that describes the activity now, not the category you hoped to be doing. Notes can add context without fragmenting the model.</p>
      </>
    ),
  },
  {
    id: "first-session",
    group: "Get Started",
    title: "Record the first session",
    summary: "Start, switch, restart and stop a live timer without creating overlaps.",
    keywords: "start first timer press switch restart stop dashboard active",
    content: (
      <>
        <h2>Start and switch</h2>
        <p>Open Dashboard and press a category. Pressing a different category closes the active session and starts the new one at the same timestamp.</p>
        <h2>Restart the same category</h2>
        <p>Pressing the currently active category closes its session and immediately starts a fresh timer of the same category. This creates a clean boundary without leaving a gap.</p>
        <h2>Stop without restarting</h2>
        <p>Use <strong>Stop timer</strong> when no new session should begin. <strong>Undo last action</strong> restores the state before the most recent supported timer or timeline mutation.</p>
        <div className="documentation-note">The active clock is live. The Today balance also updates while the timer is running.</div>
      </>
    ),
  },
  {
    id: "dashboard",
    group: "Operate",
    title: "Dashboard",
    summary: "Read service telemetry, control the active timer and review today’s balance.",
    keywords: "dashboard cpu ram disk uptime current state today balance cards unavailable telemetry reorder",
    content: (
      <>
        <h2>System telemetry</h2>
        <p>CPU, RAM, disk and uptime describe the Chronos runtime. <strong>Unavailable</strong> means the metric could not be measured; it never means zero. Storage reachability is a separate connection check and may remain available when host telemetry is not.</p>
        <h2>Current state</h2>
        <p>CURRENT STATE contains the active clock, timer actions and the four category controls. TODAY covers the local calendar day from 00:00 through the next 00:00 in the configured timezone.</p>
        <h2>Arrange cards</h2>
        <p>Drag a card by its handle or focus the handle and use its keyboard move controls. The order is stored per Chronos installation. Session history lives in Timeline rather than on Dashboard.</p>
      </>
    ),
  },
  {
    id: "timeline",
    group: "Operate",
    title: "Timeline and corrections",
    summary: "Search, add, edit, delete and export the authoritative session history.",
    keywords: "timeline session history search category filter add edit delete csv export manual note overlap",
    content: (
      <>
        <h2>Find sessions</h2>
        <p>Search notes and identifiers, filter by category and move through the result pages. Active sessions are marked as live and continue accumulating time.</p>
        <h2>Correct the record</h2>
        <ul>
          <li><strong>Add session</strong> records time that was missed.</li>
          <li><strong>Edit</strong> changes the category, timestamps or note.</li>
          <li><strong>Delete</strong> soft-deletes the session so the latest action can still be undone.</li>
        </ul>
        <p>Chronos rejects edits and manual entries that overlap another session. Start and end values are interpreted in the timezone configured in Settings.</p>
        <h2>Export</h2>
        <p>CSV export includes the current non-deleted session history in chronological form for external analysis.</p>
      </>
    ),
  },
  {
    id: "analytics",
    group: "Operate",
    title: "Analytics",
    summary: "Interpret totals, category share, daily bars and recorded-time coverage.",
    keywords: "analytics today week month last 30 days year custom range percentage coverage recorded total midnight chart",
    content: (
      <>
        <h2>Choose a period</h2>
        <p>Use Today, Week, Month, Last 30 days, Year or a custom range of up to 370 days. A day always runs from local 00:00 to the following 00:00.</p>
        <h2>How totals are calculated</h2>
        <p>Sessions are clipped at the selected boundaries. A session crossing midnight contributes only the portion inside each day. The active timer contributes through the current moment.</p>
        <h2>Coverage</h2>
        <p><strong>Recorded time</strong> is the combined duration of all session fragments inside the period. <strong>Coverage</strong> is recorded time divided by the full duration of that period. Category percentages divide the recorded time, not the wall-clock period.</p>
        <div className="documentation-note">A low coverage value is a statement about missing records, not a negative judgment about the category balance.</div>
      </>
    ),
  },
  {
    id: "telegram",
    group: "Operate",
    title: "Telegram and Gryphon",
    summary: "Connect a Gryphon-managed bot and operate Chronos from persistent Telegram controls.",
    keywords: "telegram gryphon bot link initialize command timer active today week month stop undo retype backfill",
    content: (
      <>
        <p>Gryphon owns Telegram transport, bot credentials and user identity. Chronos consumes the verified function connection; it does not store a plaintext bot token.</p>
        <h2>Connect</h2>
        <ol>
          <li>Connect the bot on the server with <code>sudo gryphon bot connect ALIAS</code>.</li>
          <li>Open Settings and use <strong>Link Chronos function</strong> to select the bot.</li>
          <li>If no Telegram user is linked, use <strong>Initialize bot</strong> and send the one-time <code>/link</code> challenge.</li>
        </ol>
        <h2>Commands</h2>
        <pre><code>{[
          "/timer                 persistent category controls",
          "/active                current active timer",
          "/today                 today's totals",
          "/week                  current week",
          "/month                 current month",
          "/stop                  stop the active timer",
          "/undo                  undo the latest timer action",
          "/retype                change the latest completed category",
          "/backfill [MINUTES]    record a completed session",
        ].join("\n")}</code></pre>
        <p>Backfill prompts for missing information, resolves the requested interval and preserves an active timer with overlapped time deducted.</p>
      </>
    ),
  },
  {
    id: "personalization",
    group: "Maintain",
    title: "Settings and personalization",
    summary: "Control timezone, formats, reminders, navigation, card order and accent color.",
    keywords: "settings personalization timezone format reminder summary accent theme sidebar navigation order cards",
    content: (
      <>
        <h2>Time and summaries</h2>
        <p>The timezone controls day boundaries, week and month ranges, reminder timing and displayed timestamps. Date and time formats affect presentation only.</p>
        <h2>Interface</h2>
        <p>Choose an accent color, keep the sidebar fixed or auto-hidden, and reorder navigation, Dashboard cards and Settings sections. Large page titles are independent of the labels in the left navigation.</p>
        <h2>Reminders</h2>
        <p>The long-timer threshold can be disabled with zero. Daily summaries use the configured local time and require a working Gryphon connection.</p>
      </>
    ),
  },
  {
    id: "access",
    group: "Maintain",
    title: "Security and access",
    summary: "Understand the Access Key, browser sessions and the boundary between Chronos and its agents.",
    keywords: "security access key login session logout authentication opaque secret token hash gryphon kernel",
    content: (
      <>
        <h2>Access Key</h2>
        <p>The Access Key is an opaque secret: enter the exact value issued for the installation. Chronos stores a verifier rather than recoverable plaintext. Changing the key invalidates existing browser sessions.</p>
        <h2>Session handling</h2>
        <p>Login creates a secure application session. Logout revokes the current session. Restore and security-sensitive maintenance can revoke every active session.</p>
        <h2>Service boundaries</h2>
        <p>Gryphon owns Telegram credentials and user links. Kernel owns machine enrollment and release coordination. Do not paste keys, tokens or one-time codes into support logs.</p>
      </>
    ),
  },
  {
    id: "backup",
    group: "Maintain",
    title: "Backup and restore",
    summary: "Create portable archives, monitor scheduled backups and restore without losing enrollment.",
    keywords: "backup restore archive neptune saturn schedule download upload postgres recovery enrollment",
    content: (
      <>
        <h2>What a backup contains</h2>
        <p>The archive contains Chronos data and settings, the Access Key verifier and retained command/Undo state. Plaintext keys, service tokens and Gryphon-owned identity data are excluded.</p>
        <h2>Manual and scheduled backups</h2>
        <p>Use Settings to create and download an archive. Neptune reports storage reachability and the latest stored backup. Saturn owns the backup schedule and its next due time.</p>
        <h2>Restore</h2>
        <p>Inspect the archive metadata before confirming. Restore replaces Chronos application data, signs out browser sessions and retains the target machine’s Kernel enrollment.</p>
        <div className="documentation-note">A process marked running is not proof of a usable backup. Check storage reachability, the latest successful archive and a real restore drill separately.</div>
      </>
    ),
  },
  {
    id: "updates",
    group: "Maintain",
    title: "Updates and agents",
    summary: "Read release state, verify agent connections and recover from a failed update.",
    keywords: "updates updater kernel register release version agent enrollment rollback job health readiness",
    content: (
      <>
        <h2>Release path</h2>
        <p>Kernel Register supplies the repository and public-domain configuration. Updater verifies a release, creates a pre-update backup and replaces the immutable Chronos image.</p>
        <h2>Connection states</h2>
        <p>Read readiness, enrollment, last seen and last successful operation as separate facts. <strong>Unknown</strong>, <strong>stale</strong> and <strong>overdue</strong> are not equivalent to zero or healthy.</p>
        <h2>Failure recovery</h2>
        <p>Keep the update job ID and redacted logs, verify rollback state, then check core readiness and public access. Do not repeat an update blindly while a previous job is unresolved.</p>
      </>
    ),
  },
  {
    id: "troubleshooting",
    group: "Maintain",
    title: "Troubleshooting",
    summary: "A compact decision path for timers, telemetry, storage, Telegram and update failures.",
    keywords: "troubleshooting unavailable error timer telemetry storage reachability telegram backup updater logs incident",
    content: (
      <>
        <h2>Timer or totals look wrong</h2>
        <p>Confirm the configured timezone, inspect the exact session boundaries in Timeline and remember that analytics clips sessions at local midnight. Use Undo only for the most recent supported mutation.</p>
        <h2>Telemetry is unavailable</h2>
        <p>Host CPU, RAM, disk and uptime require runtime access to host metrics. Storage Reachability only confirms that the external storage endpoint answered; it does not provide disk capacity telemetry.</p>
        <h2>Telegram or backup is unavailable</h2>
        <p>Check the relevant agent’s configured, enrolled, reachable and last-seen states. Then inspect the latest redacted event in Settings. Keep secret values out of screenshots and incident reports.</p>
        <h2>Escalation record</h2>
        <p>Capture the local time, affected operation, public session or job identifier, observed status and redacted error. This is enough to correlate logs without exposing credentials.</p>
      </>
    ),
  },
];

const GROUPS: DocumentationGroup[] = ["Get Started", "Operate", "Maintain"];

function documentationText(node: ReactNode): string {
  if (typeof node === "string" || typeof node === "number") return String(node);
  if (Array.isArray(node)) return node.map(documentationText).join(" ");
  if (isValidElement<{ children?: ReactNode }>(node)) return documentationText(node.props.children);
  return "";
}

export function filterDocumentation(query: string): DocumentationArticle[] {
  const normalized = query.trim().toLowerCase();
  if (!normalized) return DOCUMENTATION_ARTICLES;
  return DOCUMENTATION_ARTICLES.filter((article) =>
    `${article.title} ${article.summary} ${article.keywords} ${documentationText(article.content)}`
      .toLowerCase()
      .includes(normalized),
  );
}

export default function Documentation({ version }: { version: string }) {
  const [query, setQuery] = useState("");
  const contentRef = useRef<HTMLElement>(null);
  const visible = useMemo(() => filterDocumentation(query), [query]);
  const visibleIds = useMemo(() => new Set(visible.map((article) => article.id)), [visible]);

  const scrollToSection = (id: string) => {
    const content = contentRef.current;
    const target = document.getElementById(id);
    if (!content || !target) return;
    const top = content.scrollTop + target.getBoundingClientRect().top - content.getBoundingClientRect().top - 30;
    content.scrollTo({ top, behavior: "smooth" });
  };

  return (
    <div className="documentation-page">
      <aside className="documentation-nav">
        <div className="documentation-nav-inner">
          <input
            value={query}
            onChange={(event) => {
              setQuery(event.target.value);
              contentRef.current?.scrollTo({ top: 0 });
            }}
            type="search"
            placeholder="Search documentation"
            aria-label="Search documentation"
          />
          {GROUPS.map((group) => (
            <div className="documentation-nav-group" key={group}>
              <strong>{group}</strong>
              {DOCUMENTATION_ARTICLES
                .filter((article) => article.group === group && visibleIds.has(article.id))
                .map((article) => (
                  <button
                    type="button"
                    className="documentation-link"
                    onClick={() => scrollToSection(article.id)}
                    key={article.id}
                  >
                    {article.title}
                  </button>
                ))}
            </div>
          ))}
        </div>
      </aside>

      <main className="documentation-content" ref={contentRef}>
        <header>
          <span className="documentation-kicker">Chronos {version} / Operator Guide</span>
          <h2>Welcome To Chronos</h2>
          <p>A practical guide to recording, correcting and interpreting personal time, plus maintaining Chronos and its service connections.</p>
        </header>
        {visible.map((article) => (
          <article id={article.id} data-doc-title={`${article.title} ${article.keywords}`} key={article.id}>
            <h2>{article.title}</h2>
            <p className="documentation-summary">{article.summary}</p>
            {article.content}
          </article>
        ))}
        {!visible.length && <div className="documentation-empty">No documentation sections match this search.</div>}
      </main>
    </div>
  );
}
