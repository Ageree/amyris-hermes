import Link from "next/link";
import Image from "next/image";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { BubbleMock } from "./BubbleMock";

// The fold: asymmetric split — copy left, the dhizume mascot (the brand's face)
// right, with a real chat thread floating over her lower edge as product proof.
// Ambient rose aurora + faded hairline grid behind. Hero stack = 4 text elements
// exactly (eyebrow, headline, subtext, CTA pair). Server component; CTAs links.
export function Hero() {
  return (
    <section className="relative overflow-hidden">
      {/* ambient backdrop — purely decorative, sits behind content */}
      <div aria-hidden className="grid-lines absolute inset-0 -z-10" />
      <div aria-hidden className="aurora absolute -top-32 right-[-10%] h-[520px] w-[640px] -z-10" />

      <div className="mx-auto max-w-6xl px-6 pb-28 pt-16 sm:pt-20">
        <div className="grid items-center gap-16 lg:grid-cols-[1.1fr_0.9fr]">
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
              meet dhizume. a real assistant with a real browser. she books, buys,
              researches, and reports back in your chat.
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

          {/* the brand's face + product proof, one layered moment.
             portrait dominates; the chat thread sits low-left so her face stays clear */}
          <div className="flex justify-center lg:justify-end">
            <div className="relative w-full max-w-md">
              {/* rose halo behind dhizume */}
              <div aria-hidden className="absolute -inset-8 -z-10 rounded-[3rem] bg-[radial-gradient(closest-side,rgba(226,90,130,0.22),transparent)]" />
              <Image
                src="/dhizume/portrait.png"
                alt="dhizume, your masked-muse assistant"
                width={520}
                height={520}
                priority
                className="rise w-full rounded-[var(--radius-xl)] border border-border-strong object-cover shadow-2xl shadow-black/60"
              />
              {/* a real chat thread floating over her lower edge — small, low, off the
                 left. desktop only: on mobile the clean portrait is the brand moment. */}
              <div
                className="rise absolute -bottom-10 left-1 hidden w-[54%] max-w-[205px] sm:-left-14 sm:block"
                style={{ animationDelay: "300ms" }}
              >
                <BubbleMock />
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
