"use client";

import { useState } from "react";
import { useQuery, useAction } from "convex/react";
import { api } from "@cp/api";
import { Card, CardTitle, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { TIERS, type TierName } from "@/lib/tiers";

// the paid tiers startCheckout accepts.
type PaidTier = "pro" | "max";

const TIER_ORDER: TierName[] = ["free", "pro", "max"];

function tierSpec(name: TierName) {
  return TIERS.find((t) => t.name === name) ?? null;
}

// tiers strictly above the current one — the only valid upgrade targets.
function higherTiers(current: TierName): PaidTier[] {
  const idx = TIER_ORDER.indexOf(current);
  return TIER_ORDER.slice(idx + 1).filter(
    (t): t is PaidTier => t === "pro" || t === "max",
  );
}

export function TierCard() {
  const user = useQuery(api.app.account.currentUser);
  const usage = useQuery(api.app.usage.myUsage);
  const startCheckout = useAction(api.app.upgrade.startCheckout);

  const [banner, setBanner] = useState<string | null>(null);
  const [pending, setPending] = useState<PaidTier | null>(null);

  // wait for the user before deciding what to show.
  if (user === undefined) {
    return (
      <Card className="rise" data-testid="tier-card">
        <CardTitle as="h2">plan</CardTitle>
        <div className="mt-4 h-8 w-28 animate-pulse rounded bg-surface-2" />
      </Card>
    );
  }

  const isOperator = user?.isOperator ?? false;
  // prefer the live entitlement tier, fall back to the profile tier, then free.
  const currentTier: TierName =
    (usage?.tier ?? user?.tier ?? "free") as TierName;
  const spec = tierSpec(currentTier);

  async function handleUpgrade(tier: PaidTier) {
    setPending(tier);
    setBanner(null);
    try {
      const res = await startCheckout({ tier });
      // stub provider: surface the coming-soon message (no real redirect in v1).
      if (res.checkoutUrl && res.checkoutUrl.startsWith("http")) {
        window.location.href = res.checkoutUrl;
        return;
      }
      setBanner(res.message ?? "paid plans are launching soon — you're on free for now.");
    } catch {
      setBanner("couldn't start checkout — try again in a moment.");
    } finally {
      setPending(null);
    }
  }

  return (
    <Card className="rise" data-testid="tier-card">
      <div className="flex items-baseline justify-between gap-3">
        <CardTitle as="h2">plan</CardTitle>
        {isOperator ? (
          <Badge tone="lime">max · unlimited</Badge>
        ) : (
          <Badge tone="lime">{currentTier}</Badge>
        )}
      </div>

      <CardDescription className="mt-2">
        {isOperator
          ? "operator — every channel, no limits."
          : spec
            ? `${spec.msgQuota.toLocaleString()} messages / month. ${spec.blurb}`
            : "your current plan."}
      </CardDescription>

      {/* upgrades — operators have nothing above them. */}
      {!isOperator && (
        <UpgradeOptions
          targets={higherTiers(currentTier)}
          pending={pending}
          onUpgrade={handleUpgrade}
        />
      )}

      {banner && (
        <p
          role="status"
          className="mt-4 rounded-[var(--radius)] border border-lime/30 bg-lime/10 px-3 py-2 text-xs text-lime"
        >
          {banner} <span aria-hidden="true">👋</span>
        </p>
      )}
    </Card>
  );
}

function UpgradeOptions({
  targets,
  pending,
  onUpgrade,
}: {
  targets: PaidTier[];
  pending: PaidTier | null;
  onUpgrade: (tier: PaidTier) => void;
}) {
  if (targets.length === 0) {
    return (
      <p className="mt-5 text-xs text-faint">
        you're on the top plan. nothing to upgrade.
      </p>
    );
  }

  return (
    <div className="mt-5 flex flex-col gap-2">
      {targets.map((tier) => {
        const spec = tierSpec(tier);
        if (!spec) return null;
        const busy = pending === tier;
        return (
          <Button
            key={tier}
            variant={spec.highlight ? "primary" : "secondary"}
            size="md"
            className="justify-between"
            disabled={pending !== null}
            onClick={() => onUpgrade(tier)}
          >
            <span>
              {busy ? "starting…" : `upgrade to ${tier}`}
            </span>
            <span className="font-mono text-xs opacity-80">
              ${spec.priceUsd}/mo
            </span>
          </Button>
        );
      })}
    </div>
  );
}
