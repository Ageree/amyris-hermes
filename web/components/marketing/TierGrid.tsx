import Link from "next/link";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { TIERS, type TierSpec, type TierName } from "@/lib/tiers";

// Pricing — redesigned via the 21st.dev "dark gradient pricing" pattern, re-skinned
// to the dhizume tokens (deep-rose accent, blue-violet surfaces, lowercase voice).
// Each tier carries a gradient card, a per-tier feature checklist, channel badges,
// and a full-width CTA. The pro card is highlighted with a rose ring + "most picked".
// Tier price/quota/blurb come from the shared catalog (lib/tiers); the feature
// lists are marketing copy and live here.

interface Feature {
  text: string;
  on: boolean;
}

const FEATURES: Record<TierName, Feature[]> = {
  free: [
    { text: "imessage & telegram", on: true },
    { text: "a real browser, not just chat", on: true },
    { text: "books, buys & researches", on: true },
    { text: "file outputs — docs, decks, pdfs", on: false },
    { text: "connect gmail, calendar & apps", on: false },
    { text: "priority queue", on: false },
  ],
  pro: [
    { text: "everything in free", on: true },
    { text: "file outputs — docs, decks, pdfs", on: true },
    { text: "connect gmail, calendar & apps", on: true },
    { text: "long multi-step sessions", on: true },
    { text: "priority queue", on: true },
    { text: "proactive watching & alerts", on: false },
  ],
  max: [
    { text: "everything in pro", on: true },
    { text: "proactive watching & alerts", on: true },
    { text: "heavy automation & long runs", on: true },
    { text: "early access to new skills", on: true },
    { text: "priority support", on: true },
    { text: "all gas, no ceiling", on: true },
  ],
};

function priceLabel(tier: TierSpec): string {
  return tier.priceUsd === 0 ? "free" : `$${tier.priceUsd}`;
}

// Deterministic thousands separator — avoids toLocaleString()'s server/client
// locale mismatch (the React #418 hydration warning on the tier cards).
function withCommas(n: number): string {
  return String(n).replace(/\B(?=(\d{3})+(?!\d))/g, ",");
}

function Benefit({ text, on }: Feature) {
  return (
    <li className="flex items-center gap-2.5">
      {on ? (
        <span className="grid h-4 w-4 shrink-0 place-content-center rounded-full bg-lime text-canvas">
          <svg viewBox="0 0 24 24" className="h-2.5 w-2.5" fill="none" stroke="currentColor" strokeWidth="3.5" strokeLinecap="round" strokeLinejoin="round">
            <path d="M20 6 9 17l-5-5" />
          </svg>
        </span>
      ) : (
        <span className="grid h-4 w-4 shrink-0 place-content-center rounded-full bg-surface-3 text-faint">
          <svg viewBox="0 0 24 24" className="h-2.5 w-2.5" fill="none" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round">
            <path d="M18 6 6 18M6 6l12 12" />
          </svg>
        </span>
      )}
      <span className={cn("text-sm", on ? "text-muted" : "text-faint")}>{text}</span>
    </li>
  );
}

function TierCard({ tier }: { tier: TierSpec }) {
  const highlighted = Boolean(tier.highlight);
  return (
    <div
      className={cn(
        "relative flex h-full flex-col overflow-hidden rounded-[var(--radius-lg)] border p-7",
        "transition-[transform,border-color] duration-200 hover:-translate-y-1.5",
        highlighted
          ? "border-lime/45 bg-gradient-to-br from-surface-2 to-canvas ring-1 ring-lime/30 shadow-[0_24px_60px_-24px_rgba(226,90,130,0.45)]"
          : "border-border bg-gradient-to-br from-surface to-canvas hover:border-border-strong",
      )}
    >
      {highlighted && (
        <Badge tone="lime" className="absolute right-6 top-6">
          most picked
        </Badge>
      )}

      {/* header — tier, price, quota */}
      <div className="flex flex-col gap-3 border-b border-border pb-6">
        <span className="font-mono text-sm lowercase text-muted">{tier.label}</span>
        <div className="flex items-baseline gap-1">
          <span className="font-mono text-5xl font-semibold tracking-tight text-ink">
            {priceLabel(tier)}
          </span>
          {tier.priceUsd > 0 && (
            <span className="font-mono text-sm text-faint">/mo</span>
          )}
        </div>
        <span className="font-mono text-sm text-lime">
          {withCommas(tier.msgQuota)} messages / month
        </span>
        <p className="text-sm leading-relaxed text-muted">{tier.blurb}</p>
      </div>

      {/* feature checklist */}
      <ul className="flex flex-col gap-3.5 py-7">
        {FEATURES[tier.name].map((f) => (
          <Benefit key={f.text} {...f} />
        ))}
      </ul>

      {/* channels + CTA */}
      <div className="mt-auto flex flex-col gap-4">
        <div className="flex flex-wrap gap-2">
          {tier.channels.map((channel) => (
            <Badge key={channel} tone="muted">
              {channel}
            </Badge>
          ))}
        </div>
        <Link href="/signin" className="block">
          <Button
            variant={highlighted ? "primary" : "secondary"}
            size="md"
            className="w-full"
          >
            get started
          </Button>
        </Link>
      </div>
    </div>
  );
}

export function TierGrid() {
  return (
    <section id="pricing" className="mx-auto max-w-6xl px-6 py-24">
      <div className="reveal mx-auto mb-14 max-w-xl text-center">
        <h2 className="font-display text-4xl font-medium tracking-[-0.01em] text-ink sm:text-5xl">
          one assistant. <em className="italic text-lime">pick your headroom.</em>
        </h2>
        <p className="mx-auto mt-4 max-w-md text-base leading-relaxed text-muted">
          both imessage and telegram on every tier. start free, upgrade when you
          outgrow it.
        </p>
      </div>

      <div className="grid items-stretch gap-5 md:grid-cols-3">
        {TIERS.map((tier) => (
          <div key={tier.name} className="reveal">
            <TierCard tier={tier} />
          </div>
        ))}
      </div>
    </section>
  );
}
