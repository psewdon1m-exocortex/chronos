export interface ServiceLogsOptions { base: string; download?: string; onDownload?: () => void; beforeParam?: string; }
export function mountServiceLogs(root: HTMLElement, options: ServiceLogsOptions): () => void;
