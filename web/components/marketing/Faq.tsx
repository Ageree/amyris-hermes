// FAQ — native <details>/<summary> accordion (zero JS, keyboard-accessible by
// default). Distinct layout family. The marker chevron rotates via details[open].

interface QA {
  q: string;
  a: string;
}

const FAQS: QA[] = [
  {
    q: "is it really a browser, or just web search?",
    a: "a real browser. it loads pages, logs in, clicks, and fills forms the same way you would. search is just one of the tools it can reach for.",
  },
  {
    q: "do i need to install an app?",
    a: "no. your assistant lives in imessage or telegram. you connect once and then just text it.",
  },
  {
    q: "is my data private?",
    a: "every assistant runs in its own isolated environment. the logins you grant stay in your session and are never shared with other users.",
  },
  {
    q: "can it work inside my own accounts?",
    a: "yes. tap a link once to connect gmail, calendar, and more, and it can act inside them on your behalf.",
  },
  {
    q: "what does it cost?",
    a: "free to start, with paid tiers when you want more headroom. both channels are included on every plan.",
  },
];

export function Faq() {
  return (
    <section id="faq" className="mx-auto max-w-3xl px-6 py-24">
      <div className="reveal mb-10">
        <h2 className="font-display text-4xl font-medium tracking-[-0.01em] text-ink sm:text-5xl">
          questions, <em className="italic text-lime">answered.</em>
        </h2>
      </div>

      <div className="reveal divide-y divide-border border-y border-border">
        {FAQS.map((item) => (
          <details key={item.q} className="group py-5">
            <summary className="flex cursor-pointer list-none items-center justify-between gap-4 text-left text-base font-medium text-ink transition-colors hover:text-lime [&::-webkit-details-marker]:hidden">
              {item.q}
              <span
                aria-hidden
                className="shrink-0 text-faint transition-transform duration-200 group-open:rotate-45"
              >
                <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round">
                  <path d="M12 5v14M5 12h14" />
                </svg>
              </span>
            </summary>
            <p className="mt-3 max-w-2xl text-sm leading-relaxed text-muted">
              {item.a}
            </p>
          </details>
        ))}
      </div>
    </section>
  );
}
