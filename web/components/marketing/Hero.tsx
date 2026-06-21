import Link from "next/link";
import { Button } from "@/components/ui/button";

// The fold is the wallpaper: the dhizume throne video fills the first screen,
// unobstructed — nothing covers it. Only one short line + a single CTA sit low
// on the screen, so the top ~75% is pure animated wallpaper. The phone showcase
// lives below, on scroll.
export function Hero() {
  return (
    <section className="relative flex min-h-dvh flex-col items-center justify-end px-6 pb-24 text-center">
      <p className="rise max-w-xl text-balance text-2xl font-medium leading-snug text-ink [text-shadow:0_2px_24px_rgba(0,0,0,0.8)] sm:text-3xl">
        meet dhizume — an ai assistant who can do real things.
      </p>
      <Link href="/signin" className="rise mt-7" style={{ animationDelay: "120ms" }}>
        <Button variant="primary" size="lg">
          get started
        </Button>
      </Link>
      {/* a quiet scroll cue so the wallpaper doesn't read as a dead end */}
      <span aria-hidden className="rise mt-10 text-faint" style={{ animationDelay: "240ms" }}>
        <svg viewBox="0 0 24 24" className="h-5 w-5 animate-bounce" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
          <path d="M12 5v14M5 12l7 7 7-7" />
        </svg>
      </span>
    </section>
  );
}
