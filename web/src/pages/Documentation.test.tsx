import { describe, expect, it } from "vitest";

import { DOCUMENTATION_ARTICLES, filterDocumentation } from "./Documentation";

describe("documentation index", () => {
  it("contains a complete multi-group operator guide", () => {
    expect(DOCUMENTATION_ARTICLES.length).toBeGreaterThanOrEqual(12);
    expect(new Set(DOCUMENTATION_ARTICLES.map((article) => article.group))).toEqual(
      new Set(["Get Started", "Operate", "Maintain"]),
    );
  });

  it("finds articles by operational keywords", () => {
    expect(filterDocumentation("midnight").map((article) => article.id)).toContain("analytics");
    expect(filterDocumentation("gryphon").map((article) => article.id)).toContain("telegram");
    expect(filterDocumentation("storage reachability").map((article) => article.id)).toContain("troubleshooting");
  });
});
