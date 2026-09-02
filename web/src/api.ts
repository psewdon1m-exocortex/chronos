function csrfToken(): string {
  const item = document.cookie
    .split(";")
    .map((value) => value.trim())
    .find((value) => value.startsWith("chronos_csrf="));
  return item ? decodeURIComponent(item.slice("chronos_csrf=".length)) : "";
}


export class ApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}


export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const method = (options.method ?? "GET").toUpperCase();
  const mutation = !["GET", "HEAD", "OPTIONS"].includes(method);
  const headers = new Headers(options.headers);
  if (options.body && !(options.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  if (mutation && path !== "/api/auth/login") {
    headers.set("X-CSRF-Token", csrfToken());
  }
  const response = await fetch(path, {
    ...options,
    headers,
    cache: "no-store",
    credentials: "same-origin",
  });
  if (!response.ok) {
    if (response.status === 401 && path !== "/api/auth/login" && path !== "/api/auth/status") {
      window.dispatchEvent(new CustomEvent("chronos:unauthorized"));
    }
    let message = `Request failed with HTTP ${response.status}`;
    try {
      const body = await response.json();
      message = body.error ?? body.detail ?? message;
      if (Array.isArray(message)) {
        message = message.map((item) => item.msg).join("; ");
      }
    } catch {
      // The status text remains the recovery message for non-JSON failures.
    }
    throw new ApiError(String(message), response.status);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}


export function download(path: string): void {
  const anchor = document.createElement("a");
  anchor.href = path;
  anchor.download = "";
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
}


export async function downloadFile(path: string): Promise<string> {
  const response = await fetch(path, { cache: "no-store", credentials: "same-origin" });
  if (!response.ok) throw new ApiError(`Download failed with HTTP ${response.status}`, response.status);
  const blob = await response.blob();
  const disposition = response.headers.get("Content-Disposition") ?? "";
  const match = disposition.match(/filename="?([^";]+)"?/i);
  const filename = match?.[1] ?? "chronos-download";
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
  return filename;
}
