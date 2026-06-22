import { describe, it, expect } from "vitest";
import { TIERS, PERIOD_MS, OPERATOR_QUOTA, publicTiers, type TierName } from "./tiers";

describe("PERIOD_MS", () => {
  it("is exactly 30 days in milliseconds", () => {
    expect(PERIOD_MS).toBe(30 * 24 * 60 * 60 * 1000);
  });
});

describe("OPERATOR_QUOTA", () => {
  it("is -1 (unlimited sentinel)", () => {
    expect(OPERATOR_QUOTA).toBe(-1);
  });
});

describe("TIERS catalog", () => {
  it("contains free, pro, and max tiers", () => {
    expect(Object.keys(TIERS)).toEqual(["free", "pro", "max"]);
  });

  it("free tier has 0 price and 100 msg quota", () => {
    expect(TIERS.free.priceUsd).toBe(0);
    expect(TIERS.free.msgQuota).toBe(100);
  });

  it("pro tier has $19 price and 1000 msg quota", () => {
    expect(TIERS.pro.priceUsd).toBe(19);
    expect(TIERS.pro.msgQuota).toBe(1000);
  });

  it("max tier has $49 price and 5000 msg quota", () => {
    expect(TIERS.max.priceUsd).toBe(49);
    expect(TIERS.max.msgQuota).toBe(5000);
  });

  it("all tiers have both imessage and telegram channels", () => {
    for (const tier of Object.values(TIERS)) {
      expect(tier.channels).toEqual(["imessage", "telegram"]);
    }
  });

  it("each tier name matches its key", () => {
    for (const [key, spec] of Object.entries(TIERS)) {
      expect(spec.name).toBe(key);
    }
  });

  it("each tier has a non-empty blurb", () => {
    for (const spec of Object.values(TIERS)) {
      expect(spec.blurb.length).toBeGreaterThan(0);
    }
  });

  it("prices are in ascending order: free < pro < max", () => {
    expect(TIERS.free.priceUsd).toBeLessThan(TIERS.pro.priceUsd);
    expect(TIERS.pro.priceUsd).toBeLessThan(TIERS.max.priceUsd);
  });

  it("quotas are in ascending order: free < pro < max", () => {
    expect(TIERS.free.msgQuota).toBeLessThan(TIERS.pro.msgQuota);
    expect(TIERS.pro.msgQuota).toBeLessThan(TIERS.max.msgQuota);
  });
});

describe("publicTiers", () => {
  it("returns an array of 3 tier specs", () => {
    const result = publicTiers();
    expect(result).toHaveLength(3);
  });

  it("returns tiers in order: free, pro, max", () => {
    const result = publicTiers();
    expect(result[0].name).toBe("free");
    expect(result[1].name).toBe("pro");
    expect(result[2].name).toBe("max");
  });

  it("returns the same data as the TIERS record values", () => {
    const result = publicTiers();
    expect(result[0]).toEqual(TIERS.free);
    expect(result[1]).toEqual(TIERS.pro);
    expect(result[2]).toEqual(TIERS.max);
  });
});
