"use client";

import { useEffect, useState } from "react";
import { formatRemaining } from "@/lib/utils";

// UI-only countdown for the pairing token. Ticks once/sec via setInterval to
// re-render the label — this is a DISPLAY clock, NOT data polling (the live
// "connected" flip is driven by the myChannels Convex subscription upstream).
export function Countdown({ expiresAt }: { expiresAt: number }) {
  const [now, setNow] = useState<number>(() => Date.now());

  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);

  const remaining = expiresAt - now;
  const expired = remaining <= 0;

  return (
    <span
      className={expired ? "font-mono text-xs text-danger" : "font-mono text-xs text-faint"}
      data-testid="pair-countdown"
    >
      {expired ? "link expired" : `expires in ${formatRemaining(remaining)}`}
    </span>
  );
}
