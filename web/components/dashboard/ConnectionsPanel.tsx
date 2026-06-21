"use client";

import { useState } from "react";
import Link from "next/link";
import { useQuery, useMutation } from "convex/react";
import { api } from "@cp/api";
import { Card, CardTitle, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { StatusDot } from "@/components/ui/badge";

type Channel = "imessage" | "telegram";

// Mirror of one channels:myChannels row (control-plane returns this shape). We
// annotate the .map() callback so it stays typed regardless of how the generated
// api module's types resolve — mirrors the ConnectWizard ChannelBinding pattern.
interface ChannelRow {
  kind: Channel;
  address: string;
  verified: boolean;
}

// keep only the last 4 of a phone / chat-id; mask the rest. telegram chat-ids and
// imessage numbers are both opaque-ish strings, so a uniform tail mask reads well.
function maskAddress(address: string): string {
  const trimmed = address.trim();
  if (trimmed.length <= 4) return trimmed;
  const tail = trimmed.slice(-4);
  return `••• ${tail}`;
}

function channelLabel(kind: Channel): string {
  return kind === "imessage" ? "imessage" : "telegram";
}

export function ConnectionsPanel() {
  const channels = useQuery(api.app.channels.myChannels);

  return (
    <Card className="rise" data-testid="connections-panel">
      <div className="flex items-baseline justify-between gap-3">
        <div>
          <CardTitle as="h2">channels</CardTitle>
          <CardDescription className="mt-1">
            where your assistant reaches you
          </CardDescription>
        </div>
        {channels !== undefined && channels.length > 0 && (
          <Link
            href="/connect"
            className="shrink-0 text-xs text-muted underline-offset-4 transition-colors hover:text-lime hover:underline"
          >
            connect another
          </Link>
        )}
      </div>

      <div className="mt-5">
        {channels === undefined ? (
          <>
            {/* Polite announcement while list loads (item 13). */}
            <div role="status" aria-live="polite" aria-atomic="true" className="sr-only">
              loading channels…
            </div>
            {/* Visual skeleton — aria-hidden so it's never perceived (item 13). */}
            <LoadingRows />
          </>
        ) : channels.length === 0 ? (
          <EmptyState />
        ) : (
          <ul className="flex flex-col gap-2">
            {channels.map((c: ChannelRow) => (
              <ConnectionRow
                key={`${c.kind}:${c.address}`}
                kind={c.kind}
                address={c.address}
                verified={c.verified}
              />
            ))}
          </ul>
        )}
      </div>
    </Card>
  );
}

function LoadingRows() {
  return (
    <div className="space-y-2" aria-hidden="true">
      {[0, 1].map((i) => (
        <div
          key={i}
          className="h-12 w-full rounded-[var(--radius)] bg-surface-2"
        />
      ))}
    </div>
  );
}

function EmptyState() {
  return (
    <div className="flex flex-col items-start gap-4 rounded-[var(--radius)] border border-dashed border-border bg-surface-2/40 px-4 py-6">
      <p className="text-sm text-muted">
        no channels yet. connect imessage or telegram to start chatting.
      </p>
      {/* a Link styled as the primary button (Button is a native <button>, so we
          can't nest a Link inside it for correct navigation semantics). */}
      <Link
        href="/connect"
        className="inline-flex h-8 items-center justify-center gap-2 rounded-[var(--radius)] bg-lime px-3 text-sm font-medium text-canvas shadow-[0_0_0_1px_rgba(226,90,130,0.3)] outline-none transition-colors hover:bg-lime-dim focus-visible:ring-2 focus-visible:ring-lime"
      >
        connect a channel
      </Link>
    </div>
  );
}

function ConnectionRow({
  kind,
  address,
  verified,
}: {
  kind: Channel;
  address: string;
  verified: boolean;
}) {
  const disconnect = useMutation(api.app.channels.disconnectChannel);
  const [pending, setPending] = useState(false);
  // Polite live region message for disconnect outcome (item 12).
  const [announcement, setAnnouncement] = useState<string>("");

  async function handleDisconnect() {
    setPending(true);
    setAnnouncement("");
    try {
      await disconnect({ channel: kind, address });
      // the useQuery subscription flips the list reactively; announce success.
      setAnnouncement(`${channelLabel(kind)} disconnected`);
    } catch {
      setPending(false);
      setAnnouncement(`couldn't disconnect — try again`);
    }
  }

  const tail = address.trim().slice(-4);

  return (
    <li
      className="flex items-center justify-between gap-3 rounded-[var(--radius)] border border-border bg-surface-2 px-4 py-3"
      // Accessible row label: channel name + masked address (item 11)
      aria-label={`${channelLabel(kind)} ending in ${tail}`}
    >
      {/* Polite live region for disconnect success/failure (item 12). */}
      <div role="status" aria-live="polite" aria-atomic="true" className="sr-only">
        {announcement}
      </div>

      <div className="flex min-w-0 items-center gap-3">
        <StatusDot connected={verified} />
        <div className="min-w-0">
          <p className="font-mono text-sm text-ink">{channelLabel(kind)}</p>
          <p className="truncate font-mono text-xs text-faint">
            {/* Bullets are decorative — aria-hidden; full label is on the <li> (item 11). */}
            <span aria-hidden="true">••• </span>{tail}
            {!verified && <span className="ml-2 text-muted">· pending</span>}
          </p>
        </div>
      </div>
      <Button
        variant="ghost"
        size="sm"
        onClick={handleDisconnect}
        disabled={pending}
        aria-label={`disconnect ${channelLabel(kind)}`}
      >
        {/* "disconnecting…" matches the app's other pending labels (item 17). */}
        {pending ? "disconnecting…" : "disconnect"}
      </Button>
    </li>
  );
}
