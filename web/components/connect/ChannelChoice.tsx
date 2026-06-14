"use client";

import { Card, CardTitle, CardDescription } from "@/components/ui/card";
import { cn } from "@/lib/utils";

export type Channel = "imessage" | "telegram";

// glyph field removed — was an empty string (dead code). aria-label carries the
// accessible name on each button (item 8).
const CHOICES: { kind: Channel; title: string; description: string }[] = [
  {
    kind: "imessage",
    title: "imessage",
    description: "tap to open messages, send one line, you're paired.",
  },
  {
    kind: "telegram",
    title: "telegram",
    description: "tap start in the bot — works on any device.",
  },
];

// The channel picker — two big, equal choices. One thing per screen: pick where
// your assistant should live. Disabled while a pairing token is being minted.
export function ChannelChoice({
  onPick,
  pending,
}: {
  onPick: (channel: Channel) => void;
  pending: Channel | null;
}) {
  return (
    <div className="grid gap-4 sm:grid-cols-2" data-testid="channel-choice">
      {CHOICES.map((c) => {
        const isPending = pending === c.kind;
        const disabled = pending !== null;
        return (
          <button
            key={c.kind}
            type="button"
            disabled={disabled}
            onClick={() => onPick(c.kind)}
            data-testid={`channel-${c.kind}`}
            className={cn(
              "group text-left outline-none focus-visible:ring-2 focus-visible:ring-lime rounded-[var(--radius)]",
              "transition-transform disabled:pointer-events-none",
              !disabled && "hover:-translate-y-0.5",
            )}
            aria-label={`connect ${c.title}`}
          >
            <Card
              className={cn(
                "h-full transition-colors",
                isPending
                  ? "border-lime/40 bg-surface-2"
                  : "group-hover:border-lime/30 group-hover:bg-surface-2",
                disabled && !isPending && "opacity-50",
              )}
            >
              <CardTitle className="lowercase">{c.title}</CardTitle>
              <CardDescription className="mt-2">{c.description}</CardDescription>
              {/* Polite live region announces the in-flight "minting" state (item 8). */}
              <div role="status" aria-live="polite" aria-atomic="true" className="sr-only">
                {isPending ? "minting your link…" : ""}
              </div>
              <p className="mt-4 font-mono text-xs text-faint" aria-hidden="true">
                {isPending ? "minting your link…" : "choose →"}
              </p>
            </Card>
          </button>
        );
      })}
    </div>
  );
}
