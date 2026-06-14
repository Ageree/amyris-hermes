import Link from "next/link";
import { Card, CardTitle, CardDescription } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { TIERS, type TierSpec } from "@/lib/tiers";

// Static pricing grid rendered from the marketing-side tier mirror. Every tier
// ships BOTH channels — the channel badges make that explicit on each card. The
// pro card is highlighted. Server component; each CTA is a link to /signin.

function priceLabel(tier: TierSpec): string {
  return tier.priceUsd === 0 ? "free" : `$${tier.priceUsd}`;
}

function TierCard({ tier }: { tier: TierSpec }) {
  const highlighted = Boolean(tier.highlight);
  return (
    <Card
      className={cn(
        "relative flex h-full flex-col gap-5",
        highlighted && "border-lime/40 bg-surface-2 ring-1 ring-lime/30",
      )}
    >
      {highlighted && (
        <Badge tone="lime" className="absolute -top-3 left-6">
          most picked
        </Badge>
      )}

      <div>
        <CardTitle className="lowercase">{tier.label}</CardTitle>
        <div className="mt-3 flex items-baseline gap-1">
          <span className="font-mono text-4xl font-medium text-ink">
            {priceLabel(tier)}
          </span>
          {tier.priceUsd > 0 && (
            <span className="font-mono text-sm text-faint">/mo</span>
          )}
        </div>
      </div>

      <div className="font-mono text-sm text-muted">
        {tier.msgQuota.toLocaleString()} turns / mo
      </div>

      <CardDescription>{tier.blurb}</CardDescription>

      <div className="flex flex-wrap gap-2">
        {tier.channels.map((channel) => (
          <Badge key={channel} tone="muted">
            {channel}
          </Badge>
        ))}
      </div>

      <div className="mt-auto pt-2">
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
    </Card>
  );
}

export function TierGrid() {
  return (
    <section id="pricing" className="mx-auto max-w-5xl px-6 py-20">
      <div className="mx-auto mb-12 max-w-lg text-center">
        <h2 className="text-3xl font-medium lowercase tracking-tight text-ink sm:text-4xl">
          simple pricing
        </h2>
        <p className="mt-3 text-muted">
          both imessage &amp; telegram on every tier. start free, upgrade when
          you outgrow it.
        </p>
      </div>

      <div className="grid gap-5 md:grid-cols-3">
        {TIERS.map((tier) => (
          <TierCard key={tier.name} tier={tier} />
        ))}
      </div>
    </section>
  );
}
