import { describe, it, expect } from "vitest";
import { cn, formatRemaining } from "./utils";

describe("cn", () => {
  it("joins truthy class names with spaces", () => {
    expect(cn("a", "b", "c")).toBe("a b c");
  });

  it("drops false values", () => {
    expect(cn("a", false, "b")).toBe("a b");
  });

  it("drops null values", () => {
    expect(cn("a", null, "b")).toBe("a b");
  });

  it("drops undefined values", () => {
    expect(cn("a", undefined, "b")).toBe("a b");
  });

  it("drops empty strings", () => {
    expect(cn("a", "", "b")).toBe("a b");
  });

  it("returns empty string with no truthy args", () => {
    expect(cn(false, null, undefined)).toBe("");
  });

  it("returns empty string with no args", () => {
    expect(cn()).toBe("");
  });

  it("handles single class", () => {
    expect(cn("only")).toBe("only");
  });
});

describe("formatRemaining", () => {
  it("returns 'expired' for zero ms", () => {
    expect(formatRemaining(0)).toBe("expired");
  });

  it("returns 'expired' for negative ms", () => {
    expect(formatRemaining(-1000)).toBe("expired");
  });

  it("formats seconds only when under 1 minute", () => {
    expect(formatRemaining(45_000)).toBe("45s");
  });

  it("formats minutes and padded seconds", () => {
    expect(formatRemaining(125_000)).toBe("2m 05s");
  });

  it("formats exact minutes with 00s", () => {
    expect(formatRemaining(60_000)).toBe("1m 00s");
  });

  it("formats large values correctly", () => {
    // 10 minutes and 30 seconds = 630_000 ms
    expect(formatRemaining(630_000)).toBe("10m 30s");
  });

  it("returns seconds-only for values under 60s", () => {
    expect(formatRemaining(1_000)).toBe("1s");
  });

  it("returns '0s' for 999ms (floors to 0 seconds, but m=0 so shows seconds)", () => {
    expect(formatRemaining(999)).toBe("0s");
  });
});
