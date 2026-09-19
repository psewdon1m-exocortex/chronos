export interface UpdateOverlayOptions {
  service: string;
  component: string;
  base: string;
  installedVersion?: string;
  theme?: string;
  headers?: () => Record<string, string>;
  onComplete?: () => unknown;
}
export function openUpdateOverlay(options: UpdateOverlayOptions): () => void;
export function updateCookieHeaders(names: readonly string[], header: string): Record<string, string>;
