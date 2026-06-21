"use client";

import { useQuery } from "convex/react";
import { api } from "@cp/api";
import { StatCard, UsageIcon } from "@/components/dashboard/StatCard";
import { cn } from "@/lib/utils";

// "Jun 30" style date for the period-end label.
function formatDate(ms: number): string {
  return new Date(ms).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
  });
}

export function UsagePanel() {
  const usage = useQuery(api.app.usage.myUsage);

  return (
    <StatCard
      icon={<UsageIcon />}
      title="usage"
      subtitle="messages this period"
      data-testid="usage-panel"
    >
      {usage === undefined ? (
        // loading skeleton — aria-hidden; polite region in DashboardShell announces loading (item 13)
        <div className="space-y-3" aria-hidden="true">
          <div className="h-2 w-full rounded-full bg-surface-2" />
          <div className="h-4 w-24 rounded bg-surface-2" />
        </div>
      ) : usage === null ? (
        <p className="text-sm text-faint">no plan yet — pick a tier to begin.</p>
      ) : usage.unlimited ? (
        <UnlimitedMeter periodEnd={usage.periodEnd} />
      ) : (
        <QuotaMeter
          msgUsed={usage.msgUsed}
          msgQuota={usage.msgQuota}
          remaining={usage.remaining}
          periodEnd={usage.periodEnd}
        />
      )}
    </StatCard>
  );
}

// Unlimited plan: render as plain text, no progressbar role (item 14 — a
// progressbar without aria-valuenow is indeterminate and misleads screen readers).
function UnlimitedMeter({ periodEnd }: { periodEnd: number }) {
  return (
    <div>
      {/* Decorative full bar — aria-hidden since the text below is the real content. */}
      <div
        className="h-2 w-full overflow-hidden rounded-full bg-surface-2"
        aria-hidden="true"
      >
        <div className="h-full w-full rounded-full bg-lime" />
      </div>
      <div className="mt-3 flex items-baseline justify-between">
        <span className="font-mono text-sm text-lime">unlimited</span>
        <span className="text-xs text-faint">resets {formatDate(periodEnd)}</span>
      </div>
    </div>
  );
}

function QuotaMeter({
  msgUsed,
  msgQuota,
  remaining,
  periodEnd,
}: {
  msgUsed: number;
  msgQuota: number;
  remaining: number;
  periodEnd: number;
}) {
  // guard against a 0 quota so we never divide by zero.
  const pct =
    msgQuota > 0 ? Math.min(100, Math.round((msgUsed / msgQuota) * 100)) : 0;
  // warm the bar to danger as the user runs out of headroom.
  const low = remaining <= 0 || (msgQuota > 0 && remaining / msgQuota <= 0.1);

  return (
    <div>
      <div
        className="h-2 w-full overflow-hidden rounded-full bg-surface-2"
        role="progressbar"
        aria-label="messages used"
        aria-valuenow={msgUsed}
        aria-valuemin={0}
        aria-valuemax={msgQuota}
        aria-valuetext={`${msgUsed} of ${msgQuota} used`}
      >
        <div
          className={cn(
            "h-full rounded-full transition-[width] duration-500",
            low ? "bg-danger" : "bg-lime",
          )}
          style={{ width: `${pct}%` }}
        />
      </div>

      <div className="mt-3 flex items-baseline justify-between">
        <span className="font-mono text-sm text-ink">
          {msgUsed.toLocaleString()}
          <span className="text-faint"> / {msgQuota.toLocaleString()}</span>
        </span>
        <span
          className={cn("text-xs", low ? "text-danger" : "text-muted")}
        >
          {remaining.toLocaleString()} left
        </span>
      </div>

      <p className="mt-1 text-xs text-faint">
        resets {formatDate(periodEnd)}
      </p>
    </div>
  );
}
