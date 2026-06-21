import { HTMLAttributes, ReactNode } from "react";
import { Card, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";

// Shared dashboard card chrome so plan / usage / channels stay symmetric and
// equal-sized: same header (icon box + title + optional right slot), the same
// rose glow accent, the same hover lift. `h-full flex flex-col` lets the grid
// stretch all three to one height; the body grows to fill (`flex-1`).
//
// Pattern (icon box + ring, top-right radial glow, hover lift) adapted from 21st
// dev "dashboard stat card" inspiration, re-skinned to the dhizume tokens.
interface StatCardProps extends HTMLAttributes<HTMLDivElement> {
  icon: ReactNode;
  title: string;
  /** right side of the header row — a badge, a value, or a link. */
  headerRight?: ReactNode;
  /** one-line caption under the header. */
  subtitle?: ReactNode;
  children: ReactNode;
}

export function StatCard({
  icon,
  title,
  headerRight,
  subtitle,
  children,
  className,
  ...props
}: StatCardProps) {
  return (
    <Card
      className={cn(
        "rise group relative flex h-full flex-col overflow-hidden",
        "transition-[transform,border-color] duration-300 ease-out",
        "hover:-translate-y-0.5 hover:border-border-strong",
        className,
      )}
      {...props}
    >
      {/* rose glow, top-right, behind content; intensifies on hover. */}
      <div
        aria-hidden
        className="pointer-events-none absolute -top-20 right-0 h-44 w-2/3 rounded-full bg-[radial-gradient(closest-side,color-mix(in_oklab,var(--color-lime)_26%,transparent),transparent)] opacity-40 blur-2xl transition-opacity duration-300 group-hover:opacity-80"
      />

      <div className="relative flex flex-1 flex-col">
        <div className="flex items-start justify-between gap-3">
          <div className="flex items-center gap-3">
            <span
              aria-hidden
              className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-[var(--radius-sm)] bg-lime/10 text-lime ring-1 ring-inset ring-lime/20"
            >
              {icon}
            </span>
            <CardTitle as="h2">{title}</CardTitle>
          </div>
          {headerRight ? <div className="shrink-0">{headerRight}</div> : null}
        </div>

        {subtitle ? (
          <p className="mt-3 text-sm leading-relaxed text-muted">{subtitle}</p>
        ) : null}

        <div className="mt-5 flex flex-1 flex-col">{children}</div>
      </div>
    </Card>
  );
}

// Lucide-style line icons (inline SVG, no dep) sized for the 36px icon box.
const ICON_PROPS = {
  width: 18,
  height: 18,
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.75,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
};

export function PlanIcon() {
  // sparkles — the plan / upgrade card
  return (
    <svg {...ICON_PROPS}>
      <path d="M9.94 14.06A2 2 0 0 0 8.5 12.6L3.4 11.3a.5.5 0 0 1 0-.97L8.5 9.04a2 2 0 0 0 1.44-1.45l1.3-5.1a.5.5 0 0 1 .97 0l1.3 5.1a2 2 0 0 0 1.45 1.45l5.1 1.29a.5.5 0 0 1 0 .97l-5.1 1.3a2 2 0 0 0-1.45 1.45l-1.3 5.1a.5.5 0 0 1-.97 0z" />
      <path d="M19 3v4M21 5h-4" />
    </svg>
  );
}

export function UsageIcon() {
  // activity pulse — the usage card
  return (
    <svg {...ICON_PROPS}>
      <path d="M22 12h-3.5l-2.5 7-5-14-2.5 7H5" />
    </svg>
  );
}

export function ChannelsIcon() {
  // message square — the channels card
  return (
    <svg {...ICON_PROPS}>
      <path d="M21 15a2 2 0 0 1-2 2H8l-4 4V5a2 2 0 0 1 2-2h13a2 2 0 0 1 2 2z" />
    </svg>
  );
}
