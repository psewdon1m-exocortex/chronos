import { describe, expect, it } from "vitest";

import { CATEGORY_LABELS, duration } from "./format";

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
