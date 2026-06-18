import Link from "next/link";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { BubbleMock } from "./BubbleMock";

// The fold: asymmetric split (copy left, live chat device right) over an ambient
// lime aurora + faded hairline grid. Hero stack = 4 text elements exactly
// (eyebrow, headline, subtext, CTA pair). Server component; CTAs are links.
export function Hero() {
  return (
    <section className="relative overflow-hidden">
      {/* ambient backdrop — purely decorative, sits behind content */}
      <div aria-hidden className="grid-lines absolute inset-0 -z-10" />
      <div aria-hidden className="aurora absolute -top-32 right-[-10%] h-[520px] w-[640px] -z-10" />

      <div className="mx-auto max-w-6xl px-6 pb-24 pt-16 sm:pt-20">
        <div className="grid items-center gap-14 lg:grid-cols-[1.1fr_0.9fr]">
          <div>
            <Badge tone="lime" className="rise mb-7">
              <span aria-hidden className="inline-block h-1.5 w-1.5 rounded-full bg-lime pulse-dot" />
              live now
            </Badge>

            <h1 className="rise text-5xl font-semibold leading-[1.02] tracking-tight text-ink sm:text-6xl lg:text-7xl" style={{ animationDelay: "60ms" }}>
              your assistant,
              <br />
              on <span className="text-lime">imessage</span>
              <span className="text-faint"> &amp; </span>
              <span className="text-lime">telegram</span>.
            </h1>

            <p className="rise mt-7 max-w-md text-lg leading-relaxed text-muted" style={{ animationDelay: "120ms" }}>
              a real assistant with a real browser. it books, buys, researches,
              and reports back in your chat.
            </p>

            <div className="rise mt-9 flex flex-wrap items-center gap-3" style={{ animationDelay: "180ms" }}>
              <Link href="/signin">
                <Button variant="primary" size="lg">
                  get started
                </Button>
              </Link>
              <a href="#how">
                <Button variant="secondary" size="lg">
                  see it work
                </Button>
              </a>
            </div>
          </div>

          <div className="flex justify-center lg:justify-end">
            <BubbleMock />
          </div>
        </div>
      </div>
    </section>
  );
}
