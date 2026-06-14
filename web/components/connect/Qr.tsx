"use client";

import { useState } from "react";

const SIZE = 180;

// A scannable QR for the pairing value (telegram deep-link or raw token). Uses
// the public qrserver endpoint via a plain <img> (no qr npm dep). Degrades
// gracefully: if the image fails to load, we show the raw value as a fallback so
// the user is never stuck — the deep-link / code is always reachable elsewhere too.
export function Qr({ value, label = "qr code" }: { value: string; label?: string }) {
  const [failed, setFailed] = useState(false);

  if (!value) return null;

  const src = `https://api.qrserver.com/v1/create-qr-code/?size=${SIZE}x${SIZE}&data=${encodeURIComponent(
    value,
  )}`;

  if (failed) {
    return (
      <div
        className="flex flex-col items-center gap-2 rounded-[var(--radius)] border border-border bg-surface-2 p-4 text-center"
        style={{ width: SIZE, height: SIZE }}
        data-testid="qr-fallback"
      >
        <span className="text-xs text-faint">qr unavailable</span>
        <span className="break-all font-mono text-[10px] leading-tight text-muted">
          {value}
        </span>
      </div>
    );
  }

  return (
    <img
      src={src}
      alt={label}
      width={SIZE}
      height={SIZE}
      loading="lazy"
      onError={() => setFailed(true)}
      className="rounded-[var(--radius)] border border-border bg-ink p-2"
      data-testid="qr-img"
    />
  );
}
