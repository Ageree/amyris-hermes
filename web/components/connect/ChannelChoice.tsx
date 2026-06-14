"use client";

import { Card, CardTitle, CardDescription } from "@/components/ui/card";
import { cn } from "@/lib/utils";

export type Channel = "imessage" | "telegram";

const CHOICES: { kind: Channel; title: string; description: string; glyph: string }[] = [
  {
    kind: "imessage",
    title: "imessage",
    description: "tap to open messages, send one line, you're paired.",
    glyph: "",
  },
  {
    kind: "telegram",
    title: "telegram",
    description: "tap start in the bot — works on any device.",
    glyph: "",
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
              <div className="flex items-center gap-2">
                <span className="font-mono text-2xl text-lime" aria-hidden>
                  {c.glyph}
                </span>
                <CardTitle className="lowercase">{c.title}</CardTitle>
              </div>
              <CardDescription className="mt-2">{c.description}</CardDescription>
              <p className="mt-4 font-mono text-xs text-faint">
                {isPending ? "minting your link…" : "choose →"}
              </p>
            </Card>
          </button>
        );
      })}
    </div>
  );
}
