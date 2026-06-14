"use client";

import { useEffect, useRef, useState } from "react";
import QRCode from "qrcode";

const SIZE = 180;

// Client-side QR generation using the `qrcode` npm package (item 18 — security).
// The pairing token/deep-link is a bind-to-account credential that must NOT be
// sent to any third-party host. All encoding happens in the browser; the value
// never leaves the tab.
//
// Falls back gracefully: if canvas generation fails (very unlikely), we show
// the raw value as selectable text so the user is never stuck — the deep-link
// and code are always reachable via other UI elements too.
export function Qr({ value, label = "qr code" }: { value: string; label?: string }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    if (!value || !canvasRef.current) return;

    let cancelled = false;
    QRCode.toCanvas(canvasRef.current, value, {
      width: SIZE,
      margin: 1,
      color: {
        dark: "#0a0a0b",  // canvas color
        light: "#ededf0", // ink color — good contrast for scanning
      },
    }).then(() => {
      if (!cancelled) setFailed(false);
    }).catch(() => {
      if (!cancelled) setFailed(true);
    });

    return () => { cancelled = true; };
  }, [value]);

  if (!value) return null;

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
    <canvas
      ref={canvasRef}
      width={SIZE}
      height={SIZE}
      // Actionable alt-equivalent via aria-label (item 15).
      role="img"
      aria-label={label}
      className="rounded-[var(--radius)] border border-border bg-ink p-2"
      data-testid="qr-img"
    />
  );
}
