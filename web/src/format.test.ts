import { describe, expect, it } from "vitest";

import {
  CATEGORY_LABELS,
  bytes,
  dateInput,
  duration,
  inputDateTime,
  liveSeconds,
  localDateKey,
  zonedDateTimeToIso,
} from "./format";

describe("bytes", () => {
  it("formats bounded telemetry values", () => {
    expect(bytes(1536)).toBe("1.5 KiB");
    expect(bytes(null)).toBe("Unavailable");
  });
});

describe("duration", () => {
  it("formats compact elapsed time", () => {
    expect(duration(0)).toBe("0s");
    expect(duration(3661)).toBe("1h 1m");
    expect(duration(3661, true)).toBe("1h 1m 1s");
    expect(duration(-10)).toBe("0s");
  });
});

describe("categories", () => {
  it("keeps the four product categories fixed", () => {
    expect(CATEGORY_LABELS).toEqual({
      recovery: "Recovery",
      accumulation: "Accumulation",
      execution: "Execution",
      maintenance: "Maintenance",
    });
  });
});

describe("time zones", () => {
  it("preserves seconds while editing in the configured timezone", () => {
    expect(inputDateTime("2026-08-05T09:00:37Z", "Europe/Istanbul")).toBe(
      "2026-08-05T12:00:37",
    );
    expect(zonedDateTimeToIso("2026-08-05T12:00:37", "Europe/Istanbul")).toBe(
      "2026-08-05T09:00:37.000Z",
    );
  });

  it("uses the configured timezone for date boundaries", () => {
    const instant = new Date("2026-08-04T21:30:00Z");
    expect(dateInput(instant, "Europe/Istanbul")).toBe("2026-08-05");
    expect(localDateKey(instant.toISOString(), "Europe/Istanbul")).toBe("2026-08-05");
  });
});

describe("live timer", () => {
  it("advances from the server snapshot without using the wall clock", () => {
    expect(liveSeconds(0, 154_900)).toBe(154);
    expect(liveSeconds(42, -1000)).toBe(42);
  });
});
