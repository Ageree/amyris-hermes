"use client";

import { useEffect, useRef, useState } from "react";
import { formatRemaining } from "@/lib/utils";

// Thresholds at which we announce remaining time to screen readers (item 9).
// We do NOT make every per-second tick a live region — that would spam AT users.
const ANNOUNCE_THRESHOLDS_MS = [60_000, 30_000, 10_000]; // 1 min, 30 s, 10 s

// UI-only countdown for the pairing token. Ticks once/sec via setInterval to
// re-render the label — this is a DISPLAY clock, NOT data polling (the live
// "connected" flip is driven by the myChannels Convex subscription upstream).
export function Countdown({ expiresAt }: { expiresAt: number }) {
  const [now, setNow] = useState<number>(() => Date.now());
  // The message we surface to the sr-only live region (item 9).
  const [announcement, setAnnouncement] = useState<string>("");
  // Track which thresholds we've already announced so we don't repeat.
  const announcedRef = useRef<Set<number>>(new Set());
  const prevExpiredRef = useRef(false);

  useEffect(() => {
    // Reset threshold tracking whenever the token changes (expiresAt flips).
    announcedRef.current = new Set();
    prevExpiredRef.current = false;
    setAnnouncement("");
  }, [expiresAt]);

  useEffect(() => {
    const id = setInterval(() => {
      const ts = Date.now();
      setNow(ts);

      const remaining = expiresAt - ts;
      const expired = remaining <= 0;

      // Announce expiry once (item 9 — not color-only; text already says "link expired").
      if (expired && !prevExpiredRef.current) {
        prevExpiredRef.current = true;
        setAnnouncement("pairing link expired — get a new link to continue");
        return;
      }

      // Announce each threshold once (item 9 — coarse milestones only, not per-second).
      for (const threshold of ANNOUNCE_THRESHOLDS_MS) {
        if (remaining <= threshold && !announcedRef.current.has(threshold)) {
          announcedRef.current.add(threshold);
          setAnnouncement(
            threshold === 60_000
              ? "1 minute left to pair"
              : threshold === 30_000
                ? "30 seconds left to pair"
                : "10 seconds left to pair",
          );
        }
      }
    }, 1000);
    return () => clearInterval(id);
  }, [expiresAt]);

  const remaining = expiresAt - now;
  const expired = remaining <= 0;

  return (
    <>
      {/* Polite live region — only fires at thresholds and expiry (item 9). */}
      <div role="status" aria-live="polite" aria-atomic="true" className="sr-only">
        {announcement}
      </div>

      {/* Visual display — aria-hidden so the per-second label doesn't spam AT (item 9). */}
      <span
        className={expired ? "font-mono text-xs text-danger" : "font-mono text-xs text-faint"}
        data-testid="pair-countdown"
        aria-hidden="true"
      >
        {expired ? "link expired" : `expires in ${formatRemaining(remaining)}`}
      </span>
    </>
  );
}
