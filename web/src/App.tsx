import { useCallback, useEffect, useMemo, useState } from "react";

import { api } from "./api";
import { applyTheme } from "./format";
import Login from "./Login";
import Analytics from "./pages/Analytics";
import Dashboard from "./pages/Dashboard";
import Documentation from "./pages/Documentation";
import Settings from "./pages/Settings";
import Timeline from "./pages/Timeline";
import type { SettingsResponse, SettingsValues } from "./types";
import { ChronosMark, LoadingBlock, NoticeProvider, useNotices, useSmartHover } from "./ui";

type Destination = "dashboard" | "timeline" | "analytics" | "settings";
type View = Destination | "documentation";

const DESTINATIONS: Array<{ key: Destination; label: string }> = [
  { key: "dashboard", label: "Dashboard" },
  { key: "timeline", label: "Timeline" },
  { key: "analytics", label: "Analytics" },
  { key: "settings", label: "Settings" },
];

function validOrder(value: unknown): Destination[] {
  const expected = DESTINATIONS.map((item) => item.key);
  if (!Array.isArray(value)) return expected;
  const filtered = value.filter((item): item is Destination => expected.includes(item as Destination));
  return filtered.length === expected.length && new Set(filtered).size === expected.length ? filtered : expected;
}

function AuthenticatedApp({ onLogout }: { onLogout: () => void }) {
  const [view, setView] = useState<View>("dashboard");
  const [settings, setSettings] = useState<SettingsValues | undefined>();
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [dragged, setDragged] = useState<Destination | null>(null);
  const [drop, setDrop] = useState<{ key: Destination; after: boolean } | null>(null);
  const { notify } = useNotices();

  const loadSettings = useCallback(async () => {
    try {
      const response = await api<SettingsResponse>("/api/settings");
      setSettings(response.values);
      applyTheme(response.values.theme_accent);
    } catch (error) {
      notify("error", error instanceof Error ? error.message : "Personalization could not be loaded.");
    }
  }, [notify]);

  useEffect(() => {
    void loadSettings();
  }, [loadSettings]);

  const fixed = settings?.sidebar_auto_hide === false;
  const order = validOrder(settings?.navigation_order);
  const items = useMemo(() => order.map((key) => DESTINATIONS.find((item) => item.key === key)!), [order]);

  const commitSettings = useCallback(async (patch: Partial<SettingsValues>) => {
    if (!settings) return;
    const previous = settings;
    setSettings({ ...settings, ...patch });
    try {
      const result = await api<{ values: SettingsValues }>("/api/settings", {
        method: "PATCH",
        body: JSON.stringify(patch),
      });
      setSettings(result.values);
      applyTheme(result.values.theme_accent);
    } catch (error) {
      setSettings(previous);
      applyTheme(previous.theme_accent);
      notify("error", error instanceof Error ? error.message : "Setting could not be saved.");
      throw error;
    }
  }, [notify, settings]);

  const navigate = (destination: View) => {
    if (dragged) return;
    setView(destination);
    setMobileOpen(false);
    if (!fixed) setSidebarOpen(false);
  };

  const persistOrder = (next: Destination[]) => {
    void commitSettings({ navigation_order: next })
      .then(() => notify("success", "Navigation order saved."))
      .catch(() => undefined);
  };

  const moveItem = (key: Destination, direction: -1 | 1) => {
    const index = order.indexOf(key);
    const nextIndex = Math.max(0, Math.min(order.length - 1, index + direction));
    if (index === nextIndex) return;
    const next = [...order];
    next.splice(index, 1);
    next.splice(nextIndex, 0, key);
    persistOrder(next);
  };

  const reorder = () => {
    if (!dragged || !drop || dragged === drop.key) {
      setDragged(null);
      setDrop(null);
      return;
    }
    const next = order.filter((key) => key !== dragged);
    const index = Math.max(0, Math.min(next.length, next.indexOf(drop.key) + (drop.after ? 1 : 0)));
    next.splice(index, 0, dragged);
    persistOrder(next);
    setDragged(null);
    setDrop(null);
  };

  const logout = async () => {
    try {
      await api("/api/auth/logout", { method: "POST" });
    } finally {
      onLogout();
    }
  };

  const title = view === "documentation" ? "Documentation" : DESTINATIONS.find((item) => item.key === view)?.label ?? "Chronos";

  return (
    <div className={`app-shell ${fixed ? "sidebar-fixed" : ""}`}>
      {!fixed && <div className="sidebar-activation" onPointerEnter={() => setSidebarOpen(true)} />}
      {mobileOpen && <button className="sidebar-backdrop" aria-label="Close menu" onClick={() => setMobileOpen(false)} />}
      <aside
        className={`sidebar ${fixed || sidebarOpen || mobileOpen ? "is-open" : ""}`}
        onPointerEnter={() => setSidebarOpen(true)}
        onPointerLeave={() => !fixed && !mobileOpen && setSidebarOpen(false)}
      >
        <div className="sidebar-brand" aria-label="Chronos">
          <ChronosMark />
          <span>Chronos</span>
        </div>
        <nav className="sidebar-navigation" aria-label="Primary navigation">
          {items.map((item, index) => (
            <button
              type="button"
              key={item.key}
              className={`${view === item.key ? "is-active" : ""} ${dragged === item.key ? "is-dragging" : ""} ${drop?.key === item.key ? (drop.after ? "drop-after" : "drop-before") : ""}`}
              draggable
              onDragStart={() => setDragged(item.key)}
              onDragEnd={() => { setDragged(null); setDrop(null); }}
              onDragOver={(event) => {
                event.preventDefault();
                const rect = event.currentTarget.getBoundingClientRect();
                setDrop({ key: item.key, after: event.clientY >= rect.top + rect.height / 2 });
              }}
              onDrop={(event) => { event.preventDefault(); reorder(); }}
              onKeyDown={(event) => {
                if (!event.altKey) return;
                if (event.key === "ArrowUp") { event.preventDefault(); moveItem(item.key, -1); }
                if (event.key === "ArrowDown") { event.preventDefault(); moveItem(item.key, 1); }
              }}
              onClick={() => navigate(item.key)}
              data-smart-hover
            >
              <span>{item.label}</span>
              <span>{String(index + 1).padStart(2, "0")}</span>
            </button>
          ))}
        </nav>
        <div className="sidebar-operator">
          <button type="button" className={view === "documentation" ? "is-active" : ""} onClick={() => navigate("documentation")}>Documentation</button>
          <button type="button" onClick={() => void logout()}>Logout</button>
        </div>
      </aside>

      <main className="app-content">
        <header className="page-header">
          <button type="button" className="mobile-menu" onClick={() => setMobileOpen(!mobileOpen)} data-smart-hover>Menu</button>
          <h1>{title}</h1>
        </header>
        <div className="page-body">
          {view === "dashboard" && <Dashboard settings={settings} onSettingsChanged={setSettings} />}
          {view === "timeline" && <Timeline settings={settings} />}
          {view === "analytics" && <Analytics settings={settings} />}
          {view === "settings" && <Settings settings={settings} onSettingsChanged={setSettings} />}
          {view === "documentation" && <Documentation />}
        </div>
      </main>
    </div>
  );
}

function AppRoot() {
  const [authenticated, setAuthenticated] = useState<boolean | null>(null);
  useSmartHover();

  useEffect(() => {
    let active = true;
    Promise.all([
      api<{ authenticated: boolean }>("/api/auth/status"),
      api<{ accent: string }>("/api/public/theme"),
    ])
      .then(([status, theme]) => {
        applyTheme(theme.accent);
        if (active) setAuthenticated(status.authenticated);
      })
      .catch(() => active && setAuthenticated(false));
    const unauthorized = () => setAuthenticated(false);
    window.addEventListener("chronos:unauthorized", unauthorized);
    return () => {
      active = false;
      window.removeEventListener("chronos:unauthorized", unauthorized);
    };
  }, []);

  if (authenticated === null) return <LoadingBlock label="Connecting to Chronos..." />;
  if (!authenticated) return <Login onAuthenticated={() => setAuthenticated(true)} />;
  return <AuthenticatedApp onLogout={() => setAuthenticated(false)} />;
}

export default function App() {
  return <NoticeProvider><AppRoot /></NoticeProvider>;
}
