import { describe, expect, it, vi } from "vitest";

import { startUpdateWithLocalBackup } from "./updateFlow";


describe("startUpdateWithLocalBackup", () => {
  it("downloads the local backup before it starts the update", async () => {
    const order: string[] = [];
    const downloadBackup = vi.fn(async (path: string) => {
      order.push(`download:${path}`);
      return "chronos-backup-20260916120000.zip";
    });
    const startUpdate = vi.fn(async (version: string) => {
      order.push(`update:${version}`);
      return { id: "job-1", state: "REQUESTED" };
    });

    await expect(startUpdateWithLocalBackup("0.1.3", { downloadBackup, startUpdate })).resolves.toEqual({
      backupFilename: "chronos-backup-20260916120000.zip",
      job: { id: "job-1", state: "REQUESTED" },
    });
    expect(order).toEqual([
      "download:/api/backup/export",
      "update:0.1.3",
    ]);
  });

  it("does not start the update when the local backup cannot be downloaded", async () => {
    const failure = new Error("local download failed");
    const downloadBackup = vi.fn(async () => { throw failure; });
    const startUpdate = vi.fn(async () => ({ id: "must-not-run" }));

    await expect(startUpdateWithLocalBackup("0.1.3", { downloadBackup, startUpdate })).rejects.toBe(failure);
    expect(startUpdate).not.toHaveBeenCalled();
  });
});
