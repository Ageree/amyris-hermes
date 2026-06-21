"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { StatusDot } from "@/components/ui/badge";
import {
  telegramDeepLink,
  imessagePairLink,
  smsPairLink,
  IMESSAGE_NUMBER,
  TELEGRAM_BOT_USERNAME,
} from "@/lib/deeplinks";
import { Qr } from "./Qr";
import { Countdown } from "./Countdown";
import type { Channel } from "./ChannelChoice";

export interface PairingPanelProps {
  channel: Channel;
  token: string;
  code: string;
  expiresAt: number;
  deepLink: string | null;
  // Parent re-mints a fresh token (channels:createPairingToken) when expired.
  onRenew: () => void;
  renewing?: boolean;
}

// One waiting row, shared by both channels — the live "we're listening" cue.
// The text is already in the live region wrapping PairingPanel (ConnectWizard),
// so it will be announced when the panel first appears.
function WaitingRow({ label }: { label: string }) {
  return (
    <div className="flex items-center gap-2 text-sm text-muted" data-testid="waiting-row">
      <StatusDot connected={false} />
      <span>{label}</span>
    </div>
  );
}

// Clipboard outcome labels — "copied" / error hint (item 7).
type CopyState = "idle" | "copied" | "failed";

export function PairingPanel({
  channel,
  token,
  code,
  expiresAt,
  deepLink,
  onRenew,
  renewing = false,
}: PairingPanelProps) {
  const [copyState, setCopyState] = useState<CopyState>("idle");
  const [expired, setExpired] = useState(() => expiresAt - Date.now() <= 0);

  // Countdown reports expiry up so we can swap the CTA for "get a new link".
  // (Re-check on each render via a cheap derived flag plus the Countdown tick.)
  if (!expired && expiresAt - Date.now() <= 0) setExpired(true);

  const copyCode = async () => {
    try {
      await navigator.clipboard.writeText(`pair ${code}`);
      setCopyState("copied");
      setTimeout(() => setCopyState("idle"), 1600);
    } catch {
      // Clipboard blocked (insecure context / denied): show + announce hint (item 7).
      setCopyState("failed");
      setTimeout(() => setCopyState("idle"), 4000);
    }
  };

  // telegram: deepLink from the server, else build from the bot username, else a
  // manual /start instruction when no bot username is configured at all.
  const tgLink =
    deepLink ?? (TELEGRAM_BOT_USERNAME ? telegramDeepLink(TELEGRAM_BOT_USERNAME, token) : null);
  const qrValue = tgLink ?? token;

  return (
    <Card
      className="rise flex flex-col gap-6"
      data-testid="pairing-panel"
      data-channel={channel}
      data-token={token}
    >
      {/* expose the raw token for e2e to read the binding */}
      <span hidden data-testid="pair-token" data-token={token}>
        {token}
      </span>

      {expired ? (
        <div className="flex flex-col items-start gap-3" data-testid="pair-expired">
          <p className="text-sm text-muted">this link expired — grab a fresh one.</p>
          <Button variant="primary" onClick={onRenew} disabled={renewing} data-testid="pair-renew">
            {renewing ? "minting…" : "get a new link"}
          </Button>
        </div>
      ) : channel === "telegram" ? (
        <div className="flex flex-col gap-5">
          <div className="flex flex-col items-center gap-4">
            <Qr value={qrValue} label="qr code to pair telegram — or use the link/code below" />
            {tgLink ? (
              /*
                Telegram "open telegram" is an <a> (not <button> doing window.open)
                so it carries URL semantics, is popup-safe, and matches the iMessage
                pattern (item 10).
              */
              <a
                href={tgLink}
                target="_blank"
                rel="noopener noreferrer"
                data-testid="tg-open"
                className="inline-flex h-12 w-full items-center justify-center gap-2 rounded-[var(--radius)] bg-lime px-6 text-base font-medium text-canvas shadow-[0_0_0_1px_rgba(226,90,130,0.3)] outline-none transition-colors hover:bg-lime-dim focus-visible:ring-2 focus-visible:ring-lime"
              >
                open telegram
              </a>
            ) : (
              <div className="w-full rounded-[var(--radius)] border border-border bg-surface-2 p-4 text-center">
                <p className="text-sm text-muted">open the bot and send:</p>
                <code className="mt-2 inline-block break-all font-mono text-sm text-lime">
                  /start {token}
                </code>
              </div>
            )}
          </div>
          <WaitingRow label="waiting for you to tap start…" />
        </div>
      ) : (
        <div className="flex flex-col gap-5">
          {/* iMessage: open Messages prefilled, with an sms fallback + copyable chip. */}
          <div className="flex flex-col gap-3">
            {IMESSAGE_NUMBER ? (
              <a
                href={imessagePairLink(IMESSAGE_NUMBER, code)}
                data-testid="imessage-open"
                className="inline-flex h-12 w-full items-center justify-center gap-2 rounded-[var(--radius)] bg-lime px-6 text-base font-medium text-canvas shadow-[0_0_0_1px_rgba(226,90,130,0.3)] outline-none transition-colors hover:bg-lime-dim focus-visible:ring-2 focus-visible:ring-lime"
              >
                open messages
              </a>
            ) : null}
            {IMESSAGE_NUMBER ? (
              <a
                href={smsPairLink(IMESSAGE_NUMBER, code)}
                data-testid="sms-fallback"
                className="text-center text-sm text-muted underline-offset-4 hover:text-ink hover:underline"
              >
                no imessage? send as sms instead
              </a>
            ) : (
              <p className="text-sm text-muted">
                text <span className="font-mono text-ink">pair {code}</span> to the dhizume number.
              </p>
            )}
          </div>

          {/* The copyable mono chip — the exact line to send. */}
          <div className="flex flex-col gap-2">
            <div className="flex items-center justify-between gap-3 rounded-[var(--radius)] border border-border bg-surface-2 px-4 py-3">
              <code className="break-all font-mono text-sm text-lime" data-testid="pair-code">
                pair {code}
              </code>
              <Button
                variant="secondary"
                size="sm"
                onClick={copyCode}
                data-testid="copy-code"
                aria-label={copyState === "copied" ? "copied to clipboard" : "copy pairing code"}
              >
                {copyState === "copied" ? "copied" : "copy"}
              </Button>
            </div>

            {/* Polite live region announces copy success/failure to screen readers (item 7). */}
            <div role="status" aria-live="polite" aria-atomic="true" className="sr-only">
              {copyState === "copied" ? "copied to clipboard" : ""}
              {copyState === "failed" ? "couldn't copy — select the code manually" : ""}
            </div>

            {/* Visible hint on clipboard failure (item 7). */}
            {copyState === "failed" ? (
              <p className="text-xs text-muted" role="alert">
                couldn't copy — select the code manually
              </p>
            ) : null}
          </div>

          <WaitingRow label="waiting for your message…" />
        </div>
      )}

      <div className="flex items-center justify-between border-t border-border pt-4">
        <Countdown expiresAt={expiresAt} />
        {!expired ? (
          <button
            type="button"
            onClick={onRenew}
            disabled={renewing}
            className="font-mono text-xs text-faint outline-none transition-colors hover:text-muted focus-visible:text-ink disabled:opacity-50"
            data-testid="pair-renew-inline"
          >
            {renewing ? "minting…" : "new link"}
          </button>
        ) : null}
      </div>
    </Card>
  );
}
