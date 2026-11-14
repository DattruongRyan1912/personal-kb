import { describe, expect, it } from "vitest";

import { pathOnThisSite } from "@/lib/redirect";

describe("pathOnThisSite", () => {
  it("keeps a path of this site", () => {
    expect(pathOnThisSite("/c/abc")).toBe("/c/abc");
  });

  it("refuses anything that leaves the site, and an empty value", () => {
    for (const next of ["//evil.example", "/\\evil.example", "https://evil.example", "javascript:alert(1)", "", null]) {
      expect(pathOnThisSite(next)).toBe("/");
    }
  });
});
