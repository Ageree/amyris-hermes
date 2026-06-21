import Link from "next/link";
import { Button } from "@/components/ui/button";

// The fold is the video now: a transparent hero so the dhizume-on-her-throne
// page background shows through, unobstructed. One line of copy + a single CTA,
// centered low on the first screen (≈ viewport minus the 4rem sticky nav).
export function Hero() {
  return (
    <section className="relative flex min-h-[calc(100dvh-4rem)] flex-col items-center justify-end px-6 pb-24 text-center">
      <p
        className="rise max-w-xl text-balance text-2xl font-medium leading-snug text-ink [text-shadow:0_2px_20px_rgba(0,0,0,0.7)] sm:text-3xl"
      >
        meet dhizume — an ai assistant who can do real things.
      </p>
      <Link href="/signin" className="rise mt-7" style={{ animationDelay: "120ms" }}>
        <Button variant="primary" size="lg">
          get started
        </Button>
      </Link>
    </section>
  );
}
