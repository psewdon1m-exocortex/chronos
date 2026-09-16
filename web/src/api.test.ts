// @vitest-environment jsdom

import { afterEach, describe, expect, it, vi } from "vitest";

import { downloadFile } from "./api";


describe("downloadFile", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("copies the response into a named browser download", async () => {
    const body = new Blob(["backup-bytes"], { type: "application/zip" });
    const fetchMock = vi.fn(async () => ({
      ok: true,
      status: 200,
      headers: new Headers({
        "Content-Disposition": 'attachment; filename="chronos-backup-20260916120000.zip"',
      }),
      blob: async () => body,
    }));
    vi.stubGlobal("fetch", fetchMock);
    const createObjectURL = vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:chronos-backup");
    const revokeObjectURL = vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => undefined);
    let clickedDownload = "";
    let clickedHref = "";
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function click(this: HTMLAnchorElement) {
      clickedDownload = this.download;
      clickedHref = this.href;
    });

    await expect(downloadFile("/api/backup/export")).resolves.toBe("chronos-backup-20260916120000.zip");

    expect(fetchMock).toHaveBeenCalledWith("/api/backup/export", {
      cache: "no-store",
      credentials: "same-origin",
    });
    expect(createObjectURL).toHaveBeenCalledWith(body);
    expect(clickedDownload).toBe("chronos-backup-20260916120000.zip");
    expect(clickedHref).toBe("blob:chronos-backup");
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:chronos-backup");
    expect(document.querySelector("a")).toBeNull();
  });
});
