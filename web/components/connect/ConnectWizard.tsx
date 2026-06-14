"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useMutation, useQuery } from "convex/react";
import { api } from "@cp/api";
import { Button } from "@/components/ui/button";
import { Card, CardTitle, CardDescription } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { TIERS, type TierName } from "@/lib/tiers";
import { cn } from "@/lib/utils";
import { ChannelChoice, type Channel } from "./ChannelChoice";
import { PairingPanel } from "./PairingPanel";

// design §7 — a reactive state machine. NO polling: the "pair" step subscribes to
// myChannels and flips to "done" the instant the webhook binds the channel.
type Step = "tier" | "channel" | "pair" | "done";

// Mirror of one channels:myChannels row (control-plane returns this shape). We
// only read kind/verified here; annotating keeps the .some() callback typed even
// if the generated api module's path mapping is still resolving in the editor.
interface ChannelBinding {
  kind: Channel;
  verified: boolean;
}

interface Minted {
  token: string;
  code: string;
  expiresAt: number;
  deepLink: string | null;
}

const STEP_ORDER: Step[] = ["tier", "channel", "pair", "done"];

function StepDots({ step }: { step: Step }) {
  const idx = STEP_ORDER.indexOf(step);
  return (
    <div className="flex items-center gap-1.5" aria-hidden>
      {STEP_ORDER.map((s, i) => (
        <span
          key={s}
          className={cn(
            "h-1.5 rounded-full transition-all",
            i === idx ? "w-6 bg-lime" : i < idx ? "w-1.5 bg-lime/50" : "w-1.5 bg-border",
          )}
        />
      ))}
    </div>
  );
}

export function ConnectWizard() {
  const [step, setStep] = useState<Step>("tier");
  const [channel, setChannel] = useState<Channel | null>(null);
  const [minted, setMinted] = useState<Minted | null>(null);
  const [tierMessage, setTierMessage] = useState<string | null>(null);
  const [pendingChannel, setPendingChannel] = useState<Channel | null>(null);
  const [choosing, setChoosing] = useState<TierName | null>(null);
  const [renewing, setRenewing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const chooseTier = useMutation(api.app.tiers.chooseTier);
  const createPairingToken = useMutation(api.app.channels.createPairingToken);

  // Live binding subscription — this is the engine of the "pair → done" flip.
  const myChannels = useQuery(api.app.channels.myChannels);

  // When the chosen channel is verified, advance to "done". Driven purely by the
  // reactive query updating after the webhook writes the binding (no setInterval).
  useEffect(() => {
    if (step !== "pair" || !channel || !myChannels) return;
    const bound = myChannels.some(
      (c: ChannelBinding) => c.kind === channel && c.verified,
    );
    if (bound) setStep("done");
  }, [step, channel, myChannels]);

  const onChooseTier = async (tier: TierName) => {
    setError(null);
    setChoosing(tier);
    try {
      const res = await chooseTier({ tier });
      // paid tiers come back granted:false with a coming-soon message — the user
      // stays on free and we surface the note, then advance regardless (§7).
      setTierMessage(res.granted ? null : res.message ?? null);
      setStep("channel");
    } catch {
      setError("couldn't set your plan — try again.");
    } finally {
      setChoosing(null);
    }
  };

  const onPickChannel = async (picked: Channel) => {
    setError(null);
    setPendingChannel(picked);
    try {
      const res = await createPairingToken({ channel: picked });
      setChannel(picked);
      setMinted({
        token: res.token,
        code: res.code,
        expiresAt: res.expiresAt,
        deepLink: res.deepLink,
      });
      setStep("pair");
    } catch {
      setError("couldn't start pairing — try again.");
    } finally {
      setPendingChannel(null);
    }
  };

  const onRenew = async () => {
    if (!channel) return;
    setError(null);
    setRenewing(true);
    try {
      const res = await createPairingToken({ channel });
      setMinted({
        token: res.token,
        code: res.code,
        expiresAt: res.expiresAt,
        deepLink: res.deepLink,
      });
    } catch {
      setError("couldn't refresh the link — try again.");
    } finally {
      setRenewing(false);
    }
  };

  const startOver = () => {
    setChannel(null);
    setMinted(null);
    setError(null);
    setStep("channel");
  };

  const heading = useMemo(() => {
    switch (step) {
      case "tier":
        return "pick a plan";
      case "channel":
        return "where should it live?";
      case "pair":
        return channel === "telegram" ? "open telegram" : "open messages";
      case "done":
        return "you're connected";
    }
  }, [step, channel]);

  return (
    <div className="mx-auto flex w-full max-w-lg flex-col gap-6">
      <header className="flex flex-col gap-3">
        <div className="flex items-center justify-between">
          <Link
            href="/dashboard"
            className="font-mono text-xs text-faint outline-none transition-colors hover:text-muted focus-visible:text-ink"
          >
            ← back
          </Link>
          <StepDots step={step} />
        </div>
        <h1 className="text-2xl font-medium lowercase text-ink">{heading}</h1>
      </header>

      {error ? (
        <p className="text-sm text-danger" role="alert" data-testid="wizard-error">
          {error}
        </p>
      ) : null}

      {step === "tier" ? (
        <div className="flex flex-col gap-3" data-testid="step-tier">
          {TIERS.map((t) => (
            <button
              key={t.name}
              type="button"
              disabled={choosing !== null}
              onClick={() => onChooseTier(t.name)}
              data-testid={`tier-${t.name}`}
              className="text-left outline-none focus-visible:ring-2 focus-visible:ring-lime rounded-[var(--radius)] transition-transform hover:-translate-y-0.5 disabled:pointer-events-none disabled:opacity-60"
            >
              <Card
                className={cn(
                  "transition-colors hover:bg-surface-2",
                  t.highlight && "border-lime/30",
                )}
              >
                <div className="flex items-center justify-between gap-3">
                  <div className="flex items-center gap-2">
                    <CardTitle className="lowercase">{t.label}</CardTitle>
                    {t.highlight ? <Badge tone="lime">popular</Badge> : null}
                  </div>
                  <span className="font-mono text-sm text-ink">
                    {t.priceUsd === 0 ? "free" : `$${t.priceUsd}/mo`}
                  </span>
                </div>
                <CardDescription className="mt-2">{t.blurb}</CardDescription>
                <p className="mt-3 font-mono text-xs text-faint">
                  {t.msgQuota.toLocaleString()} messages / month
                  {choosing === t.name ? " · setting up…" : ""}
                </p>
              </Card>
            </button>
          ))}
        </div>
      ) : null}

      {step === "channel" ? (
        <div className="flex flex-col gap-4" data-testid="step-channel">
          {tierMessage ? (
            <p
              className="rounded-[var(--radius)] border border-border bg-surface-2 px-4 py-3 text-sm text-muted"
              data-testid="tier-message"
            >
              {tierMessage}
            </p>
          ) : null}
          <ChannelChoice onPick={onPickChannel} pending={pendingChannel} />
        </div>
      ) : null}

      {step === "pair" && channel && minted ? (
        <div className="flex flex-col gap-4" data-testid="step-pair">
          <PairingPanel
            channel={channel}
            token={minted.token}
            code={minted.code}
            expiresAt={minted.expiresAt}
            deepLink={minted.deepLink}
            onRenew={onRenew}
            renewing={renewing}
          />
          <button
            type="button"
            onClick={startOver}
            className="self-start font-mono text-xs text-faint outline-none transition-colors hover:text-muted focus-visible:text-ink"
            data-testid="start-over"
          >
            ← pick a different channel
          </button>
        </div>
      ) : null}

      {step === "done" ? (
        <Card className="rise flex flex-col items-start gap-4" data-testid="step-done">
          <CardTitle className="lowercase">you're connected — say hi 👋</CardTitle>
          <CardDescription>
            send a message on {channel === "telegram" ? "telegram" : "imessage"} and your
            assistant will answer. it lives where you do now.
          </CardDescription>
          <Link href="/dashboard" data-testid="done-dashboard">
            <Button variant="primary" size="lg">
              go to dashboard
            </Button>
          </Link>
        </Card>
      ) : null}
    </div>
  );
}
