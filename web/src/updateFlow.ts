import { api, downloadFile } from "./api";


export interface UpdateStartResult {
  backupFilename: string;
  job: Record<string, unknown>;
}


interface UpdateStartDependencies {
  downloadBackup: (path: string) => Promise<string>;
  startUpdate: (version: string) => Promise<Record<string, unknown>>;
}


const defaultDependencies: UpdateStartDependencies = {
  downloadBackup: (path) => downloadFile(path),
  startUpdate: (version) => api<Record<string, unknown>>("/api/updates/apply", {
    method: "POST",
    body: JSON.stringify({ version }),
  }),
};


export async function startUpdateWithLocalBackup(
  version: string,
  dependencies: UpdateStartDependencies = defaultDependencies,
): Promise<UpdateStartResult> {
  const backupFilename = await dependencies.downloadBackup("/api/backup/export");
  const job = await dependencies.startUpdate(version);
  return { backupFilename, job };
}
