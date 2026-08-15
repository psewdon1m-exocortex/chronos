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
  const timeZone = settings?.timezone;
  const format = settings?.date_format ?? "DD.MM.YYYY";
  const dateOptions: Intl.DateTimeFormatOptions =
    format === "YYYY-MM-DD"
      ? { year: "numeric", month: "2-digit", day: "2-digit", timeZone }
      : format === "MM/DD/YYYY"
        ? { month: "2-digit", day: "2-digit", year: "numeric", timeZone }
        : { day: "2-digit", month: "2-digit", year: "numeric", timeZone };
  const timeOptions: Intl.DateTimeFormatOptions = {
    hour: "2-digit",
    minute: "2-digit",
    hour12: settings?.time_format === "12h",
    timeZone,
  };
  return `${new Intl.DateTimeFormat(undefined, dateOptions).format(date)} ${new Intl.DateTimeFormat(undefined, timeOptions).format(date)}`;
}


interface ZonedParts {
  year: number;
  month: number;
  day: number;
  hour: number;
  minute: number;
  second: number;
}


function zonedParts(value: Date, timeZone: string): ZonedParts {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hourCycle: "h23",
  }).formatToParts(value);
  const part = (type: Intl.DateTimeFormatPartTypes): number =>
    Number(parts.find((item) => item.type === type)?.value ?? 0);
  return {
    year: part("year"),
    month: part("month"),
    day: part("day"),
    hour: part("hour"),
    minute: part("minute"),
    second: part("second"),
  };
}


function pad(value: number): string {
  return String(value).padStart(2, "0");
}


export function inputDateTime(value?: string | null, timeZone?: string): string {
  const date = value ? new Date(value) : new Date();
  if (timeZone) {
    const parts = zonedParts(date, timeZone);
    return `${parts.year}-${pad(parts.month)}-${pad(parts.day)}T${pad(parts.hour)}:${pad(parts.minute)}:${pad(parts.second)}`;
  }
  const offset = date.getTimezoneOffset() * 60000;
  return new Date(date.getTime() - offset).toISOString().slice(0, 19);
}


export function zonedDateTimeToIso(value: string, timeZone?: string): string {
  if (!timeZone) return new Date(value).toISOString();
  const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::(\d{2}))?$/.exec(value);
  if (!match) throw new Error("Invalid local date and time");
  const target = Date.UTC(
    Number(match[1]),
    Number(match[2]) - 1,
    Number(match[3]),
    Number(match[4]),
    Number(match[5]),
    Number(match[6] ?? 0),
  );
  let instant = target;
  for (let attempt = 0; attempt < 3; attempt += 1) {
    const parts = zonedParts(new Date(instant), timeZone);
    const represented = Date.UTC(
      parts.year,
      parts.month - 1,
      parts.day,
      parts.hour,
      parts.minute,
      parts.second,
    );
    const adjustment = target - represented;
    instant += adjustment;
    if (adjustment === 0) break;
  }
  return new Date(instant).toISOString();
}


export function localDateKey(value: string, timeZone?: string): string {
  const date = new Date(value);
  if (!timeZone) return dateInput(date);
  const parts = zonedParts(date, timeZone);
  return `${parts.year}-${pad(parts.month)}-${pad(parts.day)}`;
}


export function dateInput(value = new Date(), timeZone?: string): string {
  if (timeZone) {
    const parts = zonedParts(value, timeZone);
    return `${parts.year}-${pad(parts.month)}-${pad(parts.day)}`;
  }
  const offset = value.getTimezoneOffset() * 60000;
  return new Date(value.getTime() - offset).toISOString().slice(0, 10);
}


export function addDays(value: string, days: number): string {
  const date = new Date(`${value}T00:00:00Z`);
  date.setUTCDate(date.getUTCDate() + days);
  return date.toISOString().slice(0, 10);
}


export function liveSeconds(snapshotSeconds: number, elapsedMilliseconds: number): number {
  return Math.max(0, snapshotSeconds + Math.floor(Math.max(0, elapsedMilliseconds) / 1000));
}


export function applyTheme(dark: string, light: string, accent: string): void {
  const root = document.documentElement;
  root.style.setProperty("--dark", dark);
  root.style.setProperty("--light", light);
  root.style.setProperty("--accent", accent);
}
