import { describe, expect, it } from "vitest";

import { datesFor } from "./Analytics";


describe("analytics date presets", () => {
  const now = new Date("2026-09-02T12:00:00Z");

  it("uses one calendar date for today", () => {
    expect(datesFor("today", { timezone: "Europe/Istanbul" }, now)).toEqual({
      start: "2026-09-02",
      end: "2026-09-02",
    });
  });

  it("covers the current calendar year", () => {
    expect(datesFor("year", { timezone: "Europe/Istanbul" }, now)).toEqual({
      start: "2026-01-01",
      end: "2026-09-02",
    });
  });
});
