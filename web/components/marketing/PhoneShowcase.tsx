"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import Image from "next/image";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  SCENARIOS,
  advance,
  stepDelay,
  FINAL_STEP,
  type Rich,
} from "./phoneScenarios";

// The new fold: dhizume's telegram thread, alive. A looping demo cycles through
// 10 genuinely hard requests — she "works" (browses/applies/writes), then sends
// back a real artifact (file, table, checklist, confirmation). The phone floats
// over the throne-room video; copy + CTA sit beside it. Replaces the old hero +
// capabilities bento. Animation is pure CSS + a tiny step clock; reduced-motion
// users get the full first thread, static.

// --- rich attachment renderers -------------------------------------------------

function FileChip({ name, meta }: { name: string; meta: string }) {
  return (
    <div className="flex items-center gap-3 rounded-xl border border-border bg-surface-3 px-3 py-2.5">
      <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-lime/15 text-lime">
        <svg viewBox="0 0 24 24" className="h-4.5 w-4.5" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
          <path d="M14 3v4a1 1 0 0 0 1 1h4" />
          <path d="M17 21H7a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h7l5 5v11a2 2 0 0 1-2 2Z" />
        </svg>
      </span>
      <span className="min-w-0 flex-1">
        <span className="block truncate text-[13px] font-medium text-ink">{name}</span>
        <span className="block truncate font-mono text-[11px] text-faint">{meta}</span>
      </span>
      <svg viewBox="0 0 24 24" className="h-4 w-4 shrink-0 text-faint" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
        <path d="M12 3v12m0 0 4-4m-4 4-4-4M5 21h14" />
      </svg>
    </div>
  );
}

function MiniTable({ head, rows }: { head: string[]; rows: string[][] }) {
  return (
    <div className="overflow-hidden rounded-xl border border-border bg-surface-3">
      <table className="w-full border-collapse text-left text-[12px]">
        <thead>
          <tr>
            {head.map((h) => (
              <th key={h} className="border-b border-border px-3 py-2 font-mono text-[10px] font-normal uppercase tracking-wide text-faint">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} className={i === 0 ? "text-lime" : "text-muted"}>
              {r.map((cell, j) => (
                <td key={j} className={`px-3 py-1.5 ${j === 0 ? "font-medium text-ink" : ""} ${i === 0 && j > 0 ? "text-lime" : ""}`}>
                  {cell}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Checklist({ items }: { items: { text: string; done: boolean }[] }) {
  return (
    <ul className="flex flex-col gap-2 rounded-xl border border-border bg-surface-3 px-3 py-2.5">
      {items.map((it) => (
        <li key={it.text} className="flex items-center gap-2.5 text-[12.5px]">
          {it.done ? (
            <span className="grid h-4 w-4 shrink-0 place-content-center rounded-full bg-lime text-canvas">
              <svg viewBox="0 0 24 24" className="h-2.5 w-2.5" fill="none" stroke="currentColor" strokeWidth="3.5" strokeLinecap="round" strokeLinejoin="round">
                <path d="M20 6 9 17l-5-5" />
              </svg>
            </span>
          ) : (
            <span aria-hidden className="h-4 w-4 shrink-0 rounded-full border-2 border-lime/60" />
          )}
          <span className={it.done ? "text-muted" : "font-medium text-ink"}>{it.text}</span>
        </li>
      ))}
    </ul>
  );
}

function InfoCard({ title, lines, tag }: { title: string; lines: string[]; tag: string }) {
  return (
    <div className="rounded-xl border border-border bg-surface-3 px-3.5 py-3">
      <div className="flex items-center justify-between gap-2">
        <span className="text-[13px] font-medium text-ink">{title}</span>
        <Badge tone="lime" className="capitalize">{tag}</Badge>
      </div>
      <div className="mt-1.5 flex flex-col gap-0.5">
        {lines.map((l) => (
          <span key={l} className="text-[12px] leading-snug text-muted">{l}</span>
        ))}
      </div>
    </div>
  );
}

function RichBlock({ rich }: { rich: Rich }) {
  switch (rich.kind) {
    case "file":
      return <FileChip name={rich.name} meta={rich.meta} />;
    case "table":
      return <MiniTable head={rich.head} rows={rich.rows} />;
    case "checklist":
      return <Checklist items={rich.items} />;
    case "card":
      return <InfoCard title={rich.title} lines={rich.lines} tag={rich.tag} />;
  }
}

// --- chat primitives -----------------------------------------------------------

function UserBubble({ text }: { text: string }) {
  return (
    <div className="msg-in flex justify-end">
      <div className="max-w-[80%] rounded-2xl rounded-br-md border border-lime/20 bg-lime/15 px-3.5 py-2 text-[13px] leading-snug text-ink">
        {text}
      </div>
    </div>
  );
}

function HerBubble({ children }: { children: React.ReactNode }) {
  return (
    <div className="msg-in flex justify-start">
      <div className="max-w-[86%] rounded-2xl rounded-bl-md border border-border bg-surface-2 px-3.5 py-2 text-[13px] leading-snug text-ink">
        {children}
      </div>
    </div>
  );
}

// "dhizume is typing" — the classic three-bounce telegram indicator in her grey
// bubble, with a faint caption of what she's actually doing (browsing/applying).
function TypingIndicator({ label }: { label: string }) {
  return (
    <div className="msg-in flex flex-col items-start gap-1">
      <span className="px-1 font-mono text-[10px] text-faint">{label}</span>
      <div
        className="flex items-center gap-1.5 rounded-2xl rounded-bl-md border border-border bg-surface-2 px-4 py-3"
        aria-label="dhizume is typing"
      >
        <span className="typing-dot h-1.5 w-1.5 rounded-full bg-muted" style={{ animationDelay: "0ms" }} />
        <span className="typing-dot h-1.5 w-1.5 rounded-full bg-muted" style={{ animationDelay: "160ms" }} />
        <span className="typing-dot h-1.5 w-1.5 rounded-full bg-muted" style={{ animationDelay: "320ms" }} />
      </div>
    </div>
  );
}

// --- the device ----------------------------------------------------------------

function Phone() {
  // start fully revealed on scenario 0 so SSR / no-JS / reduced-motion all show a
  // complete thread; the clock below then holds and animates forward.
  const [{ idx, step }, setPlay] = useState({ idx: 0, step: FINAL_STEP });

  useEffect(() => {
    if (typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      return; // honor reduced-motion: stay static on the first full thread
    }
    const t = setTimeout(() => setPlay((s) => advance(s, SCENARIOS.length)), stepDelay(step));
    return () => clearTimeout(t);
  }, [idx, step]);

  const s = SCENARIOS[idx];
  const subtitle = step === 1 ? "typing…" : "online";

  return (
    <div className="relative w-full max-w-[360px]">
      {/* rose halo hugging the device */}
      <div aria-hidden className="absolute -inset-8 -z-10 rounded-[3rem] bg-[radial-gradient(closest-side,rgba(226,90,130,0.22),transparent)]" />

      <div className="rise rounded-[2.75rem] border border-border-strong bg-gradient-to-b from-surface-3 to-canvas p-2.5 shadow-2xl shadow-black/60">
        <div className="relative overflow-hidden rounded-[2.25rem] border border-border bg-canvas">
          {/* notch */}
          <div aria-hidden className="absolute left-1/2 top-2 z-20 h-5 w-28 -translate-x-1/2 rounded-full bg-canvas" />

          {/* thread header */}
          <div className="flex items-center gap-3 border-b border-border bg-surface/80 px-4 pb-3 pt-7 backdrop-blur">
            <svg viewBox="0 0 24 24" className="h-5 w-5 shrink-0 text-faint" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
              <path d="m15 18-6-6 6-6" />
            </svg>
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src="/dhizume/avatar.png" alt="" width={36} height={36} className="h-9 w-9 shrink-0 rounded-full object-cover ring-2 ring-lime/40" />
            <div className="min-w-0 flex-1">
              <div className="truncate text-[13px] font-semibold text-ink">dhizume</div>
              <div className="flex items-center gap-1.5 text-[11px] text-lime">
                <span aria-hidden className="h-1.5 w-1.5 rounded-full bg-lime pulse-dot" />
                {subtitle}
              </div>
            </div>
            <span className="font-mono text-[10px] text-faint">telegram</span>
          </div>

          {/* the conversation — fixed height, newest pinned to the bottom */}
          <div
            role="img"
            aria-label="a looping demo of a telegram chat where dhizume handles real tasks and sends back files and results"
            className="flex h-[420px] flex-col justify-end gap-2.5 bg-[radial-gradient(60%_50%_at_50%_0%,rgba(226,90,130,0.06),transparent)] px-4 py-4"
          >
            <div key={idx} className="flex flex-col gap-2.5">
              {/* step 0+: the request */}
              <UserBubble text={s.user} />
              {/* step 1: she's typing / doing the work */}
              {step === 1 && <TypingIndicator label={s.work} />}
              {/* step 2+: her reply */}
              {step >= 2 && <HerBubble>{s.reply}</HerBubble>}
              {/* step 3: the artifact */}
              {step >= 3 && (
                <HerBubble>
                  <RichBlock rich={s.rich} />
                </HerBubble>
              )}
            </div>
          </div>

          {/* faux composer */}
          <div className="flex items-center gap-2 border-t border-border bg-surface/80 px-3 py-3 backdrop-blur">
            <svg viewBox="0 0 24 24" className="h-5 w-5 shrink-0 text-faint" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
              <path d="M21.44 11.05 12.25 20.24a6 6 0 0 1-8.49-8.49l9.2-9.19a4 4 0 0 1 5.65 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48" />
            </svg>
            <div className="flex h-9 flex-1 items-center rounded-full border border-border bg-surface-2 px-4 text-[12px] text-faint">
              message
            </div>
            <span aria-hidden className="flex h-9 w-9 items-center justify-center rounded-full bg-lime text-canvas">
              <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M22 2 11 13M22 2l-7 20-4-9-9-4 20-7Z" />
              </svg>
            </span>
          </div>
        </div>
      </div>
    </div>
  );
}

// --- the fold ------------------------------------------------------------------

export function PhoneShowcase() {
  return (
    <section
      id="how"
      className="relative flex min-h-dvh items-center px-6 py-16"
    >
      <div className="mx-auto grid w-full max-w-6xl items-center gap-12 lg:grid-cols-[1fr_minmax(0,420px)] lg:gap-16">
        {/* copy */}
        <div className="order-2 text-center lg:order-1 lg:text-left">
          <Badge tone="lime" className="rise mb-6">
            <span aria-hidden className="inline-block h-1.5 w-1.5 rounded-full bg-lime pulse-dot" />
            live now
          </Badge>
          <h1 className="rise text-balance text-4xl font-semibold leading-[1.05] tracking-tight text-ink [text-shadow:0_2px_24px_rgba(0,0,0,0.75)] sm:text-5xl lg:text-6xl" style={{ animationDelay: "60ms" }}>
            she doesn&apos;t just chat.
            <br />
            she <span className="text-lime">does the work.</span>
          </h1>
          <p className="rise mx-auto mt-6 max-w-md text-balance text-lg leading-relaxed text-muted [text-shadow:0_1px_16px_rgba(0,0,0,0.7)] lg:mx-0" style={{ animationDelay: "120ms" }}>
            meet dhizume — a real assistant with a real browser, living in your
            telegram. she writes, applies, books, buys, and texts the finished
            file back.
          </p>
          <div className="rise mt-8 flex flex-wrap items-center justify-center gap-3 lg:justify-start" style={{ animationDelay: "180ms" }}>
            <Link href="/signin">
              <Button variant="primary" size="lg">get started</Button>
            </Link>
            <a href="#pricing">
              <Button variant="secondary" size="lg">see pricing</Button>
            </a>
          </div>
          <p className="rise mt-6 font-mono text-xs text-faint [text-shadow:0_1px_12px_rgba(0,0,0,0.8)]" style={{ animationDelay: "240ms" }}>
            real browser · sends real files · imessage &amp; telegram
          </p>
        </div>

        {/* the living phone — dhizume stands beside it (desktop), presenting the
            thread; her lower body fades into the dark so she reads as a figure,
            not a pasted cutout. hidden on mobile so the phone stays the hero. */}
        <div className="relative order-1 flex items-end justify-center lg:order-2 lg:justify-end">
          <Image
            src="/dhizume/figure.png"
            alt="dhizume"
            width={437}
            height={1100}
            priority
            className="pointer-events-none absolute bottom-0 left-0 z-0 hidden h-[118%] w-auto max-w-none -translate-x-[42%] select-none object-contain opacity-95 drop-shadow-[0_24px_48px_rgba(0,0,0,0.65)] [mask-image:linear-gradient(to_bottom,black_62%,transparent)] lg:block"
          />
          <div className="relative z-10">
            <Phone />
          </div>
        </div>
      </div>
    </section>
  );
}
