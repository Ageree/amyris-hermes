"use client";

import { useEffect, useRef, useState } from "react";

// "Things she'll actually finish" — a pinned, scroll-driven sequence: the section
// sticks to the viewport and the cards advance one at a time as you scroll, each
// fading up as the previous fades out. No photos — just the outcome, big and
// editorial. A numbered stepper on the left tracks where you are. Distinct layout
// family from the film split and the pricing grid. Lowercase voice, one accent.
const CARDS: ReadonlyArray<readonly [string, string]> = [
  [
    "research & long writing",
    "a 60-page cited thesis. a scientific report with 31 references in ieee style. a pitch deck with charts and speaker notes. she reads the sources, then writes the whole thing.",
  ],
  [
    "books & buys",
    "flights held under budget, the best-reviewed table reserved, the top robot vacuum compared and ordered.",
  ],
  [
    "applies to jobs",
    "tailors your résumé to each posting, applies for you, and tracks the replies as they come in.",
  ],
  [
    "works in your apps",
    "connect gmail and calendar once. she acts inside them on your behalf — no copy-paste.",
  ],
  [
    "watches & grabs",
    "follows a price or a drop and checks out the instant it dips, day or night.",
  ],
  [
    "clears your inbox",
    "reads every unread thread, flags what needs you today, archives the rest.",
  ],
];

export function RealThings() {
  const wrapRef = useRef<HTMLDivElement>(null);
  const [active, setActive] = useState(0);

  useEffect(() => {
    const wrap = wrapRef.current;
    if (!wrap) return;
    let raf = 0;
    const update = () => {
      raf = 0;
      const rect = wrap.getBoundingClientRect();
      const total = rect.height - window.innerHeight;
      // how far we've scrolled into the pinned region, clamped to [0, total]
      const scrolled = Math.min(Math.max(-rect.top, 0), Math.max(total, 1));
      const p = total > 0 ? scrolled / total : 0;
      const idx = Math.min(CARDS.length - 1, Math.floor(p * CARDS.length));
      setActive((prev) => (prev === idx ? prev : idx));
    };
    const onScroll = () => {
      if (!raf) raf = requestAnimationFrame(update);
    };
    update();
    window.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("resize", onScroll);
    return () => {
      window.removeEventListener("scroll", onScroll);
      window.removeEventListener("resize", onScroll);
      if (raf) cancelAnimationFrame(raf);
    };
  }, []);

  return (
    <section
      ref={wrapRef}
      className="relative"
      style={{ height: `${CARDS.length * 78}vh` }}
    >
      <div className="sticky top-0 flex h-[100svh] items-center overflow-hidden px-6 py-20">
        <div className="mx-auto grid w-full max-w-6xl items-center gap-10 lg:grid-cols-[0.82fr_1.18fr] lg:gap-16">
          {/* heading + numbered stepper */}
          <div>
            <h2 className="font-display text-4xl font-medium leading-[1.05] tracking-[-0.01em] text-ink sm:text-5xl">
              things she&rsquo;ll actually{" "}
              <em className="italic text-lime">finish.</em>
            </h2>
            <p className="mt-4 max-w-sm text-base leading-relaxed text-muted">
              not suggestions. not a draft you have to run yourself. the done
              thing, back in your chat.
            </p>

            <ol className="mt-10 hidden flex-col gap-3 lg:flex">
              {CARDS.map(([t], i) => (
                <li
                  key={t}
                  className={`flex items-center gap-3 text-sm transition-colors duration-300 ${
                    i === active ? "text-ink" : "text-faint"
                  }`}
                >
                  <span
                    className={`font-mono text-xs tabular-nums ${
                      i === active ? "text-lime" : "text-faint"
                    }`}
                  >
                    {String(i + 1).padStart(2, "0")}
                  </span>
                  <span
                    aria-hidden
                    className="h-px flex-none transition-all duration-300"
                    style={{
                      width: i === active ? 30 : 14,
                      background:
                        i === active
                          ? "var(--color-lime)"
                          : "var(--color-border-strong)",
                    }}
                  />
                  {t}
                </li>
              ))}
            </ol>
          </div>

          {/* card stack — only the active card is shown; the rest fade out */}
          <div className="relative min-h-[20rem] sm:min-h-[22rem]">
            {CARDS.map(([t, d], i) => (
              <article
                key={t}
                className={`absolute inset-0 flex flex-col justify-center overflow-hidden rounded-[var(--radius-lg)] border border-border bg-surface p-8 transition-all duration-500 ease-out motion-reduce:transition-none sm:p-10 ${
                  i === active
                    ? "translate-y-0 opacity-100"
                    : "pointer-events-none translate-y-6 opacity-0"
                }`}
              >
                <span
                  aria-hidden
                  className="font-display text-7xl font-medium leading-none text-lime/15 sm:text-8xl"
                >
                  {String(i + 1).padStart(2, "0")}
                </span>
                <h3 className="mt-6 font-display text-3xl font-medium text-ink sm:text-4xl">
                  {t}
                </h3>
                <p className="mt-4 max-w-md text-pretty text-base leading-relaxed text-muted">
                  {d}
                </p>
              </article>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}
