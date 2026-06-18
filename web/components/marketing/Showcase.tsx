// Real prompts people actually send — two marquee rows drifting in opposite
// directions (the page's single marquee). These are concrete, hard, lowercase
// tasks that show the browser superpower. Hover to pause; reduced-motion users
// scroll the rows by hand (overflow-x-auto). Edges fade with a mask.

const ROW_A = [
  "find 3 flights to lisbon under $400 next month and hold the cheapest",
  "book a haircut near me for saturday morning",
  "watch this product page and text me when it's back in stock",
  "compare the top 3 robot vacuums under $300 and tell me which to buy",
  "reserve a table for 4 friday at 8 somewhere with good reviews",
];

const ROW_B = [
  "summarize my unread emails from this week and flag anything urgent",
  "find the cheapest hotel near the convention center for those dates",
  "track this flight and tell me if the price drops",
  "fill out this rebate form with my details and submit it",
  "dig up the founder's contact at this company and draft an intro",
];

function Pill({ text }: { text: string }) {
  return (
    <span className="mx-2 inline-flex shrink-0 items-center gap-2 rounded-full border border-border bg-surface px-4 py-2.5 text-sm text-muted">
      <span aria-hidden className="h-1.5 w-1.5 shrink-0 rounded-full bg-lime/70" />
      {text}
    </span>
  );
}

function MarqueeRow({ items, reverse }: { items: string[]; reverse?: boolean }) {
  // duplicate the list so the -50% translate loops seamlessly
  const doubled = [...items, ...items];
  return (
    <div className="marquee overflow-x-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
      <div className={`marquee-track flex w-max ${reverse ? "reverse" : ""}`}>
        {doubled.map((text, i) => (
          <Pill key={`${text}-${i}`} text={text} />
        ))}
      </div>
    </div>
  );
}

export function Showcase() {
  return (
    <section className="py-24">
      <div className="reveal mx-auto mb-12 max-w-2xl px-6 text-center">
        <h2 className="text-3xl font-semibold tracking-tight text-ink sm:text-4xl">
          the kind of thing you can just ask
        </h2>
        <p className="mt-4 text-lg leading-relaxed text-muted">
          no prompt engineering. real requests, handled end to end.
        </p>
      </div>

      <div
        className="flex flex-col gap-4 [mask-image:linear-gradient(to_right,transparent,black_8%,black_92%,transparent)]"
        aria-label="example requests people send hermes"
      >
        <MarqueeRow items={ROW_A} />
        <MarqueeRow items={ROW_B} reverse />
      </div>
    </section>
  );
}
