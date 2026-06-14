// A faux imessage/telegram thread — purely decorative. Two human bubbles + one
// lime "assistant" reply. No state; entrance via the .rise helper (staggered
// with inline animation-delay). Server component.

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
            ? "max-w-[80%] rounded-2xl rounded-br-md bg-surface-2 px-4 py-2.5 text-sm text-ink"
            : "max-w-[80%] rounded-2xl rounded-bl-md bg-lime px-4 py-2.5 text-sm font-medium text-canvas"
        }
      >
        {children}
      </div>
    </div>
  );
}

export function BubbleMock() {
  return (
    <div
      role="img"
      aria-label="a chat thread where the assistant books a table after browsing the web"
      className="w-full max-w-sm rounded-[var(--radius)] border border-border bg-surface p-4 shadow-2xl shadow-black/40"
    >
      <div className="mb-3 flex items-center gap-2 border-b border-border pb-3">
        <span aria-hidden className="inline-block h-2 w-2 rounded-full bg-lime" />
        <span className="font-mono text-xs text-faint">hermes · imessage</span>
      </div>

      <div className="flex flex-col gap-2.5">
        <Bubble from="user" delayMs={80}>
          book a table for two at 8 tonight somewhere good nearby
        </Bubble>
        <Bubble from="assistant" delayMs={260}>
          on it — checking openings now <span aria-hidden="true">👋</span>
        </Bubble>
        <Bubble from="assistant" delayMs={460}>
          done. booked rosa at 8:15, 4 min walk. confirmation in your inbox.
        </Bubble>
      </div>
    </div>
  );
}
