export type Category = "recovery" | "accumulation" | "execution" | "maintenance";

export interface CategoryMetric {
  category: Category;
  label: string;
  seconds: number;
  percent: number;
}

export interface Session {
  id: number;
  public_id: string;
  category: Category;
  label: string;
  started_at: string;
  stopped_at: string | null;
  duration_seconds: number;
  timer_elapsed_seconds: number;
  note: string;
  source: "telegram" | "web" | "manual" | "restore";
  active: boolean;
  updated_at: string;
}

export interface Analytics {
  start: string;
  end: string;
  total_seconds: number;
  period_seconds: number;
  coverage_percent: number;
  categories: CategoryMetric[];
  days: Array<{
    date: string;
    total_seconds: number;
    categories: Record<Category, number>;
  }>;
}

export interface DashboardData {
  now: string;
  profile_name: string;
  timezone: string;
  categories: Array<{ key: Category; label: string }>;
  active: Session | null;
  today: Analytics;
  recent: Session[];
  telemetry: Telemetry;
}

export interface Telemetry {
  captured_at: number;
  cpu: { percent: number | null; logical_cores: number };
  ram: { percent: number | null; used_bytes: number | null; total_bytes: number | null };
  disk: {
    percent: number | null;
    used_bytes: number | null;
    total_bytes: number | null;
    scope: string;
  };
  uptime_seconds: number;
}

export interface SettingsValues {
  profile_name: string;
  timezone: string;
  week_starts_on: number;
  time_format: "12h" | "24h";
  date_format: "DD.MM.YYYY" | "YYYY-MM-DD" | "MM/DD/YYYY";
  reminder_minutes: number;
  daily_summary_enabled: boolean;
  daily_summary_time: string;
  theme_accent: string;
  sidebar_auto_hide: boolean;
  navigation_order: Array<"dashboard" | "timeline" | "analytics" | "settings">;
  dashboard_order: Array<"cpu" | "ram" | "disk" | "uptime" | "current" | "today" | "recent">;
  settings_order: Array<
    "appearance" | "security" | "backup" | "gryphon" | "updates" | "logs" | "personalization"
  >;
}

export interface SettingsResponse {
  values: SettingsValues;
  runtime: {
    version: string;
    public_url: string;
    repository_url: string;
    register_revision: string | null;
    kernel_url: string | null;
    kernel_reachable: boolean;
    kernel_configured: boolean;
  };
}

export interface AuditEvent {
  id: number;
  status: "success" | "error" | "denied" | "info";
  action: string;
  target: string;
  actor: string;
  message: string;
  details: Record<string, unknown>;
  request_id: string | null;
  created_at: string;
}
