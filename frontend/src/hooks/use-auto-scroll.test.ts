import { describe, expect, it } from "vitest";

import { followsAfterScroll, isNearBottom } from "@/hooks/use-auto-scroll";

describe("isNearBottom", () => {
  it("is true at the bottom and within the margin, false once the user reads above it", () => {
    expect(isNearBottom({ scrollTop: 600, scrollHeight: 1000, clientHeight: 400 })).toBe(true);
    expect(isNearBottom({ scrollTop: 560, scrollHeight: 1000, clientHeight: 400 })).toBe(true);
    expect(isNearBottom({ scrollTop: 500, scrollHeight: 1000, clientHeight: 400 })).toBe(false);
  });
});

describe("followsAfterScroll", () => {
  const at = (scrollTop: number) => ({ scrollTop, scrollHeight: 1000, clientHeight: 400 });

  it("stops following on any upward scroll, even one still within the margin", () => {
    expect(followsAfterScroll(true, 600, at(590))).toBe(false);
  });

  it("keeps following when the content shrank under a view kept at its end", () => {
    // a reset dropped the draft: the browser moved the view up to the new end
    expect(followsAfterScroll(true, 900, at(600))).toBe(true);
  });

  it("follows again once the user is back at the bottom, and not before", () => {
    expect(followsAfterScroll(false, 400, at(500))).toBe(false);
    expect(followsAfterScroll(false, 500, at(600))).toBe(true);
  });
});
