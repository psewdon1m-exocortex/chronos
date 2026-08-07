import type { Category, SettingsValues } from "./types";


export const CATEGORY_LABELS: Record<Category, string> = {
  recovery: "Recovery",
  accumulation: "Accumulation",
  execution: "Execution",
  maintenance: "Maintenance",
};


export const CATEGORY_DESCRIPTIONS: Record<Category, string> = {
  recovery: "Sleep, rest and restoration",
  accumulation: "Learning, research and preparation",
  execution: "Focused production and delivery",
  maintenance: "Administration, care and routine work",
};


export function duration(seconds: number, includeSeconds = false): string {
  const safe = Math.max(0, Math.floor(seconds));
  const days = Math.floor(safe / 86400);
  const hours = Math.floor((safe % 86400) / 3600);
  const minutes = Math.floor((safe % 3600) / 60);
  const secs = safe % 60;
  const parts: string[] = [];
  if (days) parts.push(`${days}d`);
  if (hours || days) parts.push(`${hours}h`);
  if (minutes || hours || days) parts.push(`${minutes}m`);
  if (includeSeconds || !parts.length) parts.push(`${secs}s`);
  return parts.join(" ");
}


export function localDate(value: string, settings?: Partial<SettingsValues>): string {
  const date = new Date(value);
  const format = settings?.date_format ?? "DD.MM.YYYY";
  const dateOptions: Intl.DateTimeFormatOptions =
    format === "YYYY-MM-DD"
      ? { year: "numeric", month: "2-digit", day: "2-digit" }
      : format === "MM/DD/YYYY"
        ? { month: "2-digit", day: "2-digit", year: "numeric" }
        : { day: "2-digit", month: "2-digit", year: "numeric" };
  const timeOptions: Intl.DateTimeFormatOptions = {
    hour: "2-digit",
    minute: "2-digit",
    hour12: settings?.time_format === "12h",
  };
  return `${new Intl.DateTimeFormat(undefined, dateOptions).format(date)} ${new Intl.DateTimeFormat(undefined, timeOptions).format(date)}`;
}


export function inputDateTime(value?: string | null): string {
  const date = value ? new Date(value) : new Date();
  const offset = date.getTimezoneOffset() * 60000;
  return new Date(date.getTime() - offset).toISOString().slice(0, 16);
}


export function dateInput(value = new Date()): string {
  const offset = value.getTimezoneOffset() * 60000;
  return new Date(value.getTime() - offset).toISOString().slice(0, 10);
}


export function applyTheme(dark: string, light: string, accent: string): void {
  const root = document.documentElement;
  root.style.setProperty("--dark", dark);
  root.style.setProperty("--light", light);
  root.style.setProperty("--accent", accent);
}

