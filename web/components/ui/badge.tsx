import { HTMLAttributes } from "react";
import { cn } from "@/lib/utils";

type Tone = "neutral" | "lime" | "muted";

const tones: Record<Tone, string> = {
  neutral: "bg-surface-2 text-ink border-border",
  lime: "bg-lime/15 text-lime border-lime/30",
  muted: "bg-transparent text-faint border-border",
};

export function Badge({
  className,
  tone = "neutral",
  ...props
}: HTMLAttributes<HTMLSpanElement> & { tone?: Tone }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-mono",
        tones[tone],
        className,
      )}
      {...props}
    />
  );
}

// The live connection dot: lime + pulsing while waiting, solid lime once bound.
export function StatusDot({ connected }: { connected: boolean }) {
  return (
    <span
      aria-hidden
      className={cn(
        "inline-block h-2 w-2 rounded-full",
        connected ? "bg-lime" : "bg-faint pulse-dot",
      )}
    />
  );
}
