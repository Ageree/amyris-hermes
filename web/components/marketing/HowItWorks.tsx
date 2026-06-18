import Link from "next/link";
import { Button } from "@/components/ui/button";

// "how it works" — a connected 3-step flow (a horizontal track on desktop, a
// vertical stack on mobile). Distinct layout family from the bento above. The
// verb-noun step titles ARE the labels (no "step 1 / step 2" prefixes).

interface Step {
  n: string;
  title: string;
  body: string;
}

const STEPS: Step[] = [
  {
    n: "1",
    title: "pick a channel",
    body: "connect imessage or telegram in one tap. your assistant spins up the moment you do.",
  },
  {
    n: "2",
    title: "text it like a person",
    body: "no commands, no syntax. say what you want in plain words, the way you would text a friend.",
  },
  {
    n: "3",
    title: "it goes and does it",
    body: "it opens a real browser, works the task, and texts back the result. you stay in the chat.",
  },
];

export function HowItWorks() {
  return (
    <section id="how" className="relative border-y border-border bg-surface/40">
      <div className="mx-auto max-w-6xl px-6 py-24">
        <div className="reveal mx-auto max-w-2xl text-center">
          <h2 className="text-3xl font-semibold tracking-tight text-ink sm:text-4xl">
            from sign-up to done in three texts
          </h2>
          <p className="mt-4 text-lg leading-relaxed text-muted">
            no app to install. it lives where you already are.
          </p>
        </div>

        <ol className="relative mt-16 grid gap-10 md:grid-cols-3 md:gap-6">
          {/* the connecting track sits behind the number row on desktop only */}
          <div
            aria-hidden
            className="absolute left-0 right-0 top-5 hidden h-px bg-gradient-to-r from-transparent via-border-strong to-transparent md:block"
          />
          {STEPS.map((step) => (
            <li key={step.n} className="reveal relative flex flex-col items-start gap-4 md:items-center md:text-center">
              <span className="relative z-10 flex h-10 w-10 items-center justify-center rounded-full border border-lime/40 bg-canvas font-mono text-sm text-lime shadow-[0_0_0_4px_var(--color-canvas)]">
                {step.n}
              </span>
              <div className="md:px-4">
                <h3 className="text-lg font-medium tracking-tight text-ink">
                  {step.title}
                </h3>
                <p className="mt-2 max-w-xs text-sm leading-relaxed text-muted">
                  {step.body}
                </p>
              </div>
            </li>
          ))}
        </ol>

        <div className="reveal mt-14 flex justify-center">
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
