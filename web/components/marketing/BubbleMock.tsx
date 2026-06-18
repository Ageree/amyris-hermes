// The hero's product preview: a polished chat thread where the assistant takes a
// genuinely hard request, BROWSES the live web, and reports a concrete result.
// This is the product itself (a chat), not a fake dashboard — bubbles are how
// imessage/telegram actually render. Decorative (role="img"); entrance staggered
// via .rise, with a perpetual typing indicator and a "browsing" working chip.

interface BubbleProps {
  from: "user" | "assistant";
  delayMs: number;
  children: React.ReactNode;
}

function Bubble({ from, delayMs, children }: BubbleProps) {
  const isUser = from === "user";
  return (
    <div
      className={`rise flex ${isUser ? "justify-end" : "justify-start"}`}
      style={{ animationDelay: `${delayMs}ms` }}
    >
      <div
        className={
          isUser
            ? "max-w-[82%] rounded-2xl rounded-br-md bg-surface-3 px-4 py-2.5 text-[13px] leading-snug text-ink"
            : "max-w-[82%] rounded-2xl rounded-bl-md bg-lime px-4 py-2.5 text-[13px] font-medium leading-snug text-canvas"
        }
      >
        {children}
      </div>
    </div>
  );
}

// A "hermes is doing real work in a browser" chip — animated dots, no emoji.
function WorkingChip({ delayMs }: { delayMs: number }) {
  return (
    <div
      className="rise flex justify-start"
      style={{ animationDelay: `${delayMs}ms` }}
    >
      <div className="inline-flex items-center gap-2 rounded-full border border-border bg-surface-2 px-3 py-1.5">
        <span className="font-mono text-[11px] text-faint">browsing</span>
        <span className="flex items-center gap-0.5" aria-hidden>
          <span className="typing-dot h-1 w-1 rounded-full bg-lime" style={{ animationDelay: "0ms" }} />
          <span className="typing-dot h-1 w-1 rounded-full bg-lime" style={{ animationDelay: "180ms" }} />
          <span className="typing-dot h-1 w-1 rounded-full bg-lime" style={{ animationDelay: "360ms" }} />
        </span>
        <span className="font-mono text-[11px] text-faint">4 sites</span>
      </div>
    </div>
  );
}

export function BubbleMock() {
  return (
    <div className="relative w-full max-w-sm">
      {/* a soft lime halo hugging the device */}
      <div
        aria-hidden
        className="absolute -inset-6 -z-10 rounded-[2rem] bg-[radial-gradient(closest-side,rgba(198,242,78,0.18),transparent)]"
      />
      <div
        role="img"
        aria-label="a chat thread where hermes browses the web and books a dentist appointment"
        className="rise w-full overflow-hidden rounded-[var(--radius-xl)] border border-border-strong bg-surface/90 shadow-2xl shadow-black/50 backdrop-blur"
      >
        {/* thread header */}
        <div className="flex items-center justify-between border-b border-border px-4 py-3">
          <div className="flex items-center gap-2.5">
            <span aria-hidden className="relative inline-flex h-2 w-2 items-center justify-center">
              <span className="absolute h-2 w-2 rounded-full bg-lime/60 ping-ring" />
              <span className="relative h-1.5 w-1.5 rounded-full bg-lime pulse-dot" />
            </span>
            <span className="font-mono text-xs text-ink">hermes</span>
          </div>
          <span className="font-mono text-[10px] tracking-tight text-faint">
            imessage
          </span>
        </div>

        {/* the conversation */}
        <div className="flex flex-col gap-2.5 px-4 py-4">
          <Bubble from="user" delayMs={120}>
            find a highly-rated dentist near fidi open saturday and book a cleaning
          </Bubble>
          <Bubble from="assistant" delayMs={340}>
            on it, searching now
          </Bubble>
          <WorkingChip delayMs={560} />
          <Bubble from="assistant" delayMs={820}>
            booked. dr. amara okafor, sat 10:30am, 0.3mi away. calendar invite sent to your inbox.
          </Bubble>
        </div>

        {/* faux composer */}
        <div className="flex items-center gap-2 border-t border-border px-4 py-3">
          <div className="flex h-8 flex-1 items-center rounded-full border border-border bg-surface-2 px-3.5 font-mono text-[11px] text-faint">
            imessage
          </div>
          <span
            aria-hidden
            className="flex h-8 w-8 items-center justify-center rounded-full bg-lime text-canvas"
          >
            <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M12 19V5M5 12l7-7 7 7" />
            </svg>
          </span>
        </div>
      </div>
    </div>
  );
}
