import { v } from "convex/values";

// ---------------------------------------------------------------------------
// Data-driven tier catalog (design §5). ONE source of truth for prices, quotas,
// and channels so the landing, the entitlement grant, and the quota gate never
// drift. BOTH channels (imessage + telegram) are on EVERY tier (locked operator
// decision #3). Quotas/prices are the goal.md defaults; the operator overrides by
// editing this file. The operator (user #0) gets `max` with an UNLIMITED quota
// (msgQuota === -1) via OPERATOR_QUOTA, never one of these caps.
// ---------------------------------------------------------------------------

export const PERIOD_MS = 30 * 24 * 60 * 60 * 1000; // rolling 30-day window

export type TierName = "free" | "pro" | "max";

export interface TierSpec {
  name: TierName;
  label: string;
  priceUsd: number; // monthly; 0 = free
  msgQuota: number; // assistant turns per period
  channels: ("imessage" | "telegram")[];
  blurb: string;
}

// free: 100 turns; pro: 1000 @ $19; max: 5000 @ $49 (goal.md defaults).
export const TIERS: Record<TierName, TierSpec> = {
  free: {
    name: "free",
    label: "free",
    priceUsd: 0,
    msgQuota: 100,
    channels: ["imessage", "telegram"],
    blurb: "kick the tires — a real assistant on imessage or telegram.",
  },
  pro: {
    name: "pro",
    label: "pro",
    priceUsd: 19,
    msgQuota: 1000,
    channels: ["imessage", "telegram"],
    blurb: "daily driver — plenty of headroom for real work.",
  },
  max: {
    name: "max",
    label: "max",
    priceUsd: 49,
    msgQuota: 5000,
    channels: ["imessage", "telegram"],
    blurb: "all gas — heavy automation and long sessions.",
  },
};

export const OPERATOR_QUOTA = -1; // unlimited (sentinel; the quota gate never blocks it)

export const tierValidator = v.union(
  v.literal("free"),
  v.literal("pro"),
  v.literal("max"),
);

// Public catalog shape the landing/dashboard renders (no server internals).
export function publicTiers(): TierSpec[] {
  return [TIERS.free, TIERS.pro, TIERS.max];
}
