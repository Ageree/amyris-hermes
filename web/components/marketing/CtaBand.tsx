import Link from "next/link";
import { Button } from "@/components/ui/button";

// Closing CTA — a centered band over a soft lime aurora. Single primary action
// (signup intent, same "get started" label used across the page). Distinct
// layout family: full-width centered moment, not a card grid.
export function CtaBand() {
  return (
    <section className="relative overflow-hidden border-t border-border">
      <div aria-hidden className="aurora absolute inset-x-0 -top-24 mx-auto h-[420px] w-[760px]" />
      <div className="reveal relative mx-auto max-w-3xl px-6 py-28 text-center">
        <h2 className="font-display text-5xl font-medium leading-[1.04] tracking-[-0.01em] text-ink sm:text-6xl">
          your assistant is <em className="italic text-lime">one text away.</em>
        </h2>
        <p className="mx-auto mt-5 max-w-md text-base leading-relaxed text-muted sm:text-lg">
          free to start. she lives in the chat you already use.
        </p>
        <div className="mt-9 flex justify-center">
          <Link href="/signin">
            <Button variant="primary" size="lg">
              get started
            </Button>
          </Link>
        </div>
      </div>
    </section>
  );
}
