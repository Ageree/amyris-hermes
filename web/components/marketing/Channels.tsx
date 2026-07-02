// "Lives where you already text" — a slim centered band naming the two channels
// with their real brand marks (Simple Icons, self-hosted in /public/logos).
// Distinct layout family: a single centered moment, not a card grid.
export function Channels() {
  return (
    <section className="border-t border-border">
      <div className="reveal mx-auto max-w-3xl px-6 py-20 text-center sm:py-24">
        <h2 className="font-display text-4xl font-medium leading-[1.06] tracking-[-0.01em] text-ink sm:text-5xl">
          no app to install.
          <br />
          she&rsquo;s already <em className="italic text-lime">where you text.</em>
        </h2>
        <p className="mx-auto mt-5 max-w-md text-base leading-relaxed text-muted">
          connect once, then just message her. both channels are included on every plan.
        </p>

        <div className="mt-10 flex items-center justify-center gap-4 sm:gap-5">
          {[
            { src: "/logos/imessage.svg", label: "imessage" },
            { src: "/logos/telegram.svg", label: "telegram" },
          ].map((c) => (
            <div
              key={c.label}
              className="inline-flex items-center gap-3 rounded-full border border-border bg-surface px-5 py-3"
            >
              <img src={c.src} alt="" aria-hidden className="h-6 w-6" />
              <span className="text-sm font-medium text-ink">{c.label}</span>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
