export interface BackupPolicyOptions {
  service: string;
  base: string;
  headers?: () => Record<string, string>;
}
export function mountBackupPolicy(root: HTMLElement, options: BackupPolicyOptions): () => void;
