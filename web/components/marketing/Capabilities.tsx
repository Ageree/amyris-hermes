// The differentiator. A bento with rhythm: one wide hero tile ("a real browser,
// not a chatbot") + four concrete capability tiles. Two cells carry real visual
// variation (gradient + a mono url motif) so it never reads as white-on-white.
// Section header is a stacked headline + short body (no split-header, no eyebrow).

interface Cap {
  kicker: string;
  title: string;
  body: string;
}

const CAPS: Cap[] = [
  {
    kicker: "books & reserves",
    title: "it fills the form, not a suggestion box",
    body: "tables, appointments, tickets. it works the booking flow end to end and confirms back.",
  },
  {
    kicker: "shops & compares",
    title: "finds it, prices it, buys on your word",
    body: "compares options across stores, holds the cheapest, and checks out only when you say go.",
  },
  {
    kicker: "researches deep",
    title: "the answer, not ten blue links",
    body: "reads dozens of pages and hands back a decision you can act on in one message.",
  },
  {
    kicker: "connects your apps",
    title: "gmail, calendar, and more in one tap",
    body: "tap a link once and it acts inside your accounts, no copy-pasting tokens.",
  },
];

function CapabilityTile({ cap }: { cap: Cap }) {
  return (
    <div className="reveal group flex flex-col gap-3 rounded-[var(--radius-lg)] border border-border bg-surface p-6 transition-colors hover:border-border-strong hover:bg-surface-2">
      <span className="font-mono text-xs tracking-tight text-lime">
        {cap.kicker}
      </span>
      <h3 className="text-lg font-medium leading-snug tracking-tight text-ink">
        {cap.title}
      </h3>
      <p className="text-sm leading-relaxed text-muted">{cap.body}</p>
    </div>
  );
}

export function Capabilities() {
  return (
    <section id="capabilities" className="mx-auto max-w-6xl px-6 py-24">
      <div className="reveal max-w-2xl">
        <h2 className="text-3xl font-semibold tracking-tight text-ink sm:text-4xl">
          most assistants can only talk. this one acts.
        </h2>
        <p className="mt-4 text-lg leading-relaxed text-muted">
          dhizume drives a real browser the way you do. it logs in, clicks, fills
          forms, and reads what is actually on the page.
        </p>
      </div>

      <div className="mt-12 grid gap-4 lg:grid-cols-3">
        {/* wide hero tile — gradient + a mono url motif (visual variation) */}
        <div className="reveal relative flex flex-col justify-between overflow-hidden rounded-[var(--radius-lg)] border border-lime/25 bg-[linear-gradient(150deg,rgba(226,90,130,0.12),transparent_55%)] p-7 lg:col-span-2 lg:row-span-1">
          <div className="absolute inset-x-0 bottom-0 h-px bg-gradient-to-r from-transparent via-lime/40 to-transparent" />
          <div className="max-w-md">
            <h3 className="text-2xl font-semibold tracking-tight text-ink sm:text-3xl">
              a real browser, not a chatbot.
            </h3>
            <p className="mt-3 text-[15px] leading-relaxed text-muted">
              the difference between an assistant that drafts an email and one
              that actually sends it, books the table, and watches for the reply.
            </p>
          </div>
          <div className="mt-8 flex items-center gap-2 rounded-full border border-border bg-canvas/60 px-3.5 py-2 font-mono text-xs text-faint backdrop-blur">
            <span className="h-2 w-2 rounded-full bg-lime pulse-dot" aria-hidden />
            <span className="text-muted">opentable.com</span>
            <span className="text-faint">/ booking / confirm</span>
          </div>
        </div>

        {/* first capability tile sits beside the hero tile */}
        <CapabilityTile cap={CAPS[0]} />

        {/* remaining three fill the next row exactly */}
        {CAPS.slice(1).map((cap) => (
          <CapabilityTile key={cap.kicker} cap={cap} />
        ))}
      </div>
    </section>
  );
}
