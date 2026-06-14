// Marketing-side mirror of the control-plane tier catalog (control-plane/convex/
// billing/tiers.ts). The landing renders this statically (it may be unauthed/SSR,
// before any Convex call). The dashboard prefers the live `tiers:listTiers` query;
// keep this in sync with the server catalog (free 100 / pro 1000 @ $19 / max 5000 @ $49).
export type TierName = "free" | "pro" | "max";

export interface TierSpec {
  name: TierName;
  label: string;
  priceUsd: number;
  msgQuota: number;
  channels: ("imessage" | "telegram")[];
  blurb: string;
  highlight?: boolean;
}

export const TIERS: TierSpec[] = [
  {
    name: "free",
    label: "free",
    priceUsd: 0,
    msgQuota: 100,
    channels: ["imessage", "telegram"],
    blurb: "kick the tires — a real assistant on imessage or telegram.",
  },
  {
    name: "pro",
    label: "pro",
    priceUsd: 19,
    msgQuota: 1000,
    channels: ["imessage", "telegram"],
    blurb: "daily driver — plenty of headroom for real work.",
    highlight: true,
  },
  {
    name: "max",
    label: "max",
    priceUsd: 49,
    msgQuota: 5000,
    channels: ["imessage", "telegram"],
    blurb: "all gas — heavy automation and long sessions.",
  },
];
