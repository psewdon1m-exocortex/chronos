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
import { LoadingBlock, NoticeProvider, useNotices, useSmartHover } from "./ui";


type Destination = "dashboard" | "timeline" | "analytics" | "settings";
type View = Destination | "documentation";

const DESTINATIONS: Array<{ key: Destination; label: string }> = [
  { key: "dashboard", label: "Dashboard" },
  { key: "timeline", label: "Timeline" },
  { key: "analytics", label: "Analytics" },
  { key: "settings", label: "Settings" },
];


function validOrder(value: unknown): Destination[] {
  if (!Array.isArray(value)) return DESTINATIONS.map((item) => item.key);
  const known = new Set(DESTINATIONS.map((item) => item.key));
  const values = value.filter((item): item is Destination => typeof item === "string" && known.has(item as Destination));
  for (const item of DESTINATIONS) if (!values.includes(item.key)) values.push(item.key);
  return values.slice(0, DESTINATIONS.length);
}


function AuthenticatedApp({ onLogout }: { onLogout: () => void }) {
  const [view, setView] = useState<View>("dashboard");
  const [settings, setSettings] = useState<SettingsValues | undefined>();
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [order, setOrder] = useState<Destination[]>(() => {
    try {
      return validOrder(JSON.parse(localStorage.getItem("chronos.navigation.order") ?? "null"));
    } catch {
      return validOrder(null);
    }
  });
  const [dragged, setDragged] = useState<Destination | null>(null);
  const [drop, setDrop] = useState<{ key: Destination; after: boolean } | null>(null);
  const { notify } = useNotices();

  const loadSettings = useCallback(async () => {
    try {
      const response = await api<SettingsResponse>("/api/settings");
      setSettings(response.values);
      applyTheme(response.values.theme_dark, response.values.theme_light, response.values.theme_accent);
    } catch (error) {
      notify("error", error instanceof Error ? error.message : "Personalization could not be loaded.");
    }
  }, [notify]);

  useEffect(() => {
    void loadSettings();
  }, [loadSettings]);

  const fixed = settings?.sidebar_auto_hide === false;
  const items = useMemo(
    () => order.map((key) => DESTINATIONS.find((item) => item.key === key)!),
    [order],
  );

  const navigate = (destination: View) => {
    if (dragged) return;
    setView(destination);
    setMobileOpen(false);
    if (!fixed) setSidebarOpen(false);
  };

  const reorder = () => {
    if (!dragged || !drop || dragged === drop.key) {
      setDragged(null);
      setDrop(null);
      return;
    }
    const next = order.filter((key) => key !== dragged);
    let index = next.indexOf(drop.key) + (drop.after ? 1 : 0);
    index = Math.max(0, Math.min(index, next.length));
    next.splice(index, 0, dragged);
    setOrder(next);
    localStorage.setItem("chronos.navigation.order", JSON.stringify(next));
    notify("success", "Navigation order saved.");
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

  const title = view === "documentation"
    ? "Documentation"
    : DESTINATIONS.find((item) => item.key === view)?.label ?? "Chronos";

  return (
    <div className={`app-shell ${fixed ? "sidebar-fixed" : ""}`}>
      {!fixed && <div className="sidebar-activation" onPointerEnter={() => setSidebarOpen(true)} />}
      <aside
        className={`sidebar ${fixed || sidebarOpen || mobileOpen ? "is-open" : ""}`}
        onPointerEnter={() => setSidebarOpen(true)}
        onPointerLeave={() => !fixed && setSidebarOpen(false)}
      >
        <div className="sidebar-brand" aria-label="Chronos">CHRONOS</div>
        <nav className="sidebar-navigation" aria-label="Primary navigation">
          {items.map((item, index) => (
            <button
              type="button"
              key={item.key}
              className={`${view === item.key ? "is-active" : ""} ${dragged === item.key ? "is-dragging" : ""} ${drop?.key === item.key ? (drop.after ? "drop-after" : "drop-before") : ""}`}
              draggable
              onDragStart={() => setDragged(item.key)}
              onDragEnd={() => {
                setDragged(null);
                setDrop(null);
              }}
              onDragOver={(event) => {
                event.preventDefault();
                const rect = event.currentTarget.getBoundingClientRect();
                setDrop({ key: item.key, after: event.clientY >= rect.top + rect.height / 2 });
              }}
              onDrop={(event) => {
                event.preventDefault();
                reorder();
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
          <button type="button" className={view === "documentation" ? "is-active" : ""} onClick={() => navigate("documentation")} data-smart-hover>
            Documentation
          </button>
          <button type="button" onClick={() => void logout()} data-smart-hover>Logout</button>
        </div>
      </aside>

      <main className="app-content">
        <header className="page-header">
          <button type="button" className="mobile-menu" onClick={() => setMobileOpen(!mobileOpen)} data-smart-hover>MENU</button>
          <h1>{title.toUpperCase()}</h1>
          <span className="page-context">PERSONAL TIME / {settings?.timezone ?? "UTC"}</span>
        </header>
        {view === "dashboard" && <Dashboard settings={settings} onOpenTimeline={() => navigate("timeline")} />}
        {view === "timeline" && <Timeline settings={settings} />}
        {view === "analytics" && <Analytics settings={settings} />}
        {view === "settings" && (
          <Settings
            onSettingsChanged={(value) => {
              setSettings(value);
              applyTheme(value.theme_dark, value.theme_light, value.theme_accent);
            }}
          />
        )}
        {view === "documentation" && <Documentation />}
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
      api<{ dark: string; light: string; accent: string }>("/api/public/theme"),
    ])
      .then(([status, theme]) => {
        applyTheme(theme.dark, theme.light, theme.accent);
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
  return (
    <NoticeProvider>
      <AppRoot />
    </NoticeProvider>
  );
}
