// The centerpiece: a real rendered film of dhizume working in imessage (built
// with HyperFrames, an HTML-to-MP4 renderer — every frame is a deterministic
// capture, not a div mockup). It loops inside a clean iphone frame; the keyed
// dhizume figure stands beside it — an alpha-channel video of her typing on her
// phone (chroma-keyed: vp9-alpha webm for chromium, hevc-alpha mov for safari,
// transparent png poster as the floor). Asymmetric split: copy left, device right.
// This is the #how anchor (the film IS how it works).
//
// The screen content (status bar, imessage ui, bubbles, typing, rich results)
// is baked into the MP4. The phone bezel here is just device chrome.
export function Film() {
  return (
    <section id="how" className="relative overflow-hidden px-6 py-24 sm:py-32">
      <div className="mx-auto grid max-w-6xl items-center gap-14 lg:grid-cols-[0.92fr_1.08fr] lg:gap-10">
        {/* copy */}
        <div className="reveal max-w-lg">
          <h2 className="font-display text-4xl font-medium leading-[1.05] tracking-[-0.01em] text-ink sm:text-5xl lg:text-6xl">
            watch her actually <em className="italic text-lime">do it.</em>
          </h2>
          <p className="mt-6 max-w-md text-pretty text-base leading-relaxed text-muted sm:text-lg">
            real requests, a real browser, real results. she takes the task in
            your chat, does the work, and texts back the finished thing.
          </p>

          <dl className="mt-9 grid max-w-md grid-cols-1 gap-x-8 gap-y-5 sm:grid-cols-2">
            {[
              ["reads the web", "loads pages, logs in, clicks, fills forms."],
              ["sends real files", "docs, decks, and pdfs land in the thread."],
              ["books & buys", "flights held, tables reserved, orders placed."],
              ["keeps watch", "tracks a price or a drop, acts the moment it dips."],
            ].map(([t, d]) => (
              <div key={t}>
                <dt className="text-sm font-medium text-ink">{t}</dt>
                <dd className="mt-1 text-sm leading-relaxed text-faint">{d}</dd>
              </div>
            ))}
          </dl>
        </div>

        {/* device + figure */}
        <div className="reveal relative flex justify-center lg:justify-end">
          {/* keyed standing figure — animated, transparent, behind + left of
              the phone (desktop only). she stands and types on her phone. */}
          <video
            aria-hidden
            className="pointer-events-none absolute -left-6 bottom-0 z-0 hidden h-[116%] w-auto select-none opacity-95 lg:block"
            autoPlay
            muted
            loop
            playsInline
            preload="metadata"
            poster="/dhizume/figure-hero-poster.png"
          >
            <source src="/dhizume/figure-hero.webm" type="video/webm" />
            <source src="/dhizume/figure-hero.mov" type='video/mp4; codecs="hvc1"' />
          </video>

          {/* soft rose glow under the device */}
          <div
            aria-hidden
            className="pointer-events-none absolute left-1/2 top-1/2 -z-0 h-[120%] w-[80%] -translate-x-1/2 -translate-y-1/2 rounded-full bg-lime/10 blur-3xl"
          />

          {/* iphone */}
          <div className="relative z-10 w-[270px] shrink-0 rounded-[2.75rem] border border-border-strong bg-[#0b0a0f] p-2.5 shadow-[0_40px_90px_-30px_rgba(0,0,0,0.9),0_0_0_1px_rgba(255,255,255,0.04)_inset] sm:w-[300px]">
            {/* dynamic island */}
            <div
              aria-hidden
              className="absolute left-1/2 top-[18px] z-20 h-[26px] w-[92px] -translate-x-1/2 rounded-full bg-black"
            />
            <video
              className="aspect-[9/19.5] w-full rounded-[2.2rem] object-cover"
              autoPlay
              muted
              loop
              playsInline
              preload="metadata"
              poster="/dhizume/film-imessage.jpg"
            >
              <source src="/dhizume/film-imessage.mp4" type="video/mp4" />
            </video>
          </div>
        </div>
      </div>
    </section>
  );
}
