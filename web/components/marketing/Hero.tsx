import Link from "next/link";
import { Button } from "@/components/ui/button";

// The fold: dhizume on her moonlit throne fills the screen (VideoBackground sits
// fixed behind everything). The editorial hero block sits low-left so it never
// covers her face in the video; a left/bottom scrim keeps the copy readable.
// Display headline in Cormorant (the romantic serif), italic emphasis in the
// same family. Four text elements max, CTA visible without scroll, no scroll cue.
export function Hero() {
  return (
    <section className="relative flex min-h-dvh flex-col justify-end px-6 pb-20 sm:px-10 sm:pb-24 lg:px-16">
      {/* extra contrast wash, low-left on desktop, bottom on mobile */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 bg-[radial-gradient(120%_80%_at_15%_100%,rgba(10,8,16,0.78),transparent_60%)] sm:bg-[radial-gradient(80%_90%_at_0%_100%,rgba(10,8,16,0.82),transparent_55%)]"
      />

      <div className="rise relative mx-auto w-full max-w-6xl text-center sm:mx-0 sm:max-w-2xl sm:text-left">
        <p className="font-mono text-xs uppercase tracking-[0.32em] text-lime">
          meet dhizume
        </p>

        <h1 className="font-display mt-5 text-balance text-5xl font-medium leading-[1.04] tracking-[-0.01em] text-ink [text-shadow:0_2px_30px_rgba(0,0,0,0.7)] sm:text-6xl lg:text-7xl">
          she doesn&rsquo;t just reply.
          <br />
          she <em className="italic text-lime">does the work.</em>
        </h1>

        <p className="mx-auto mt-6 max-w-md text-pretty text-base leading-relaxed text-muted [text-shadow:0_1px_16px_rgba(0,0,0,0.7)] sm:mx-0 sm:text-lg">
          a real assistant with a real browser. she researches, books, buys, and
          texts the finished work right back to you.
        </p>

        <div className="mt-9 flex flex-col items-center gap-3 sm:flex-row sm:items-stretch">
          <Link href="/signin">
            <Button variant="primary" size="lg" className="w-full sm:w-auto">
              get started
            </Button>
          </Link>
          <a href="#how">
            <Button
              variant="secondary"
              size="lg"
              className="w-full bg-surface-2/70 backdrop-blur-md sm:w-auto"
            >
              watch her work
            </Button>
          </a>
        </div>
      </div>
    </section>
  );
}
