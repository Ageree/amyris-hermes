import Link from "next/link";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { BubbleMock } from "./BubbleMock";

// The fold. Oversized lowercase headline + subcopy about a REAL assistant with
// a REAL browser, primary CTA, and the decorative chat mock beside it. Server
// component — CTAs are plain links.
export function Hero() {
  return (
    <section className="mx-auto max-w-5xl px-6 pb-20 pt-16 sm:pt-24">
      <div className="grid items-center gap-12 lg:grid-cols-[1.15fr_1fr]">
        <div className="rise">
          <Badge tone="lime" className="mb-6">
            <span
              aria-hidden
              className="inline-block h-1.5 w-1.5 rounded-full bg-lime pulse-dot"
            />
            live now
          </Badge>

          <h1 className="font-sans text-4xl font-medium leading-[1.05] tracking-tight text-ink sm:text-6xl lg:text-7xl">
            your assistant.
            <br />
            on <span className="text-lime">imessage</span> &amp;{" "}
            <span className="text-lime">telegram</span>.
          </h1>

          <p className="mt-6 max-w-md text-base leading-relaxed text-muted sm:text-lg">
            a real assistant with a real browser. it books, buys, digs through
            the web, and reports back — right in the chat you already use. just
            text it.
          </p>

          <div className="mt-8 flex flex-wrap items-center gap-3">
            <Link href="/signin">
              <Button variant="primary" size="lg">
                get started
              </Button>
            </Link>
            <span className="font-mono text-sm text-faint">
              free to start · no app to install
            </span>
          </div>
        </div>

        <div className="flex justify-center lg:justify-end">
          <BubbleMock />
        </div>
      </div>
    </section>
  );
}
