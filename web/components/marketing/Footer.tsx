import Link from "next/link";

// Tiny restrained footer — mono wordmark, lowercase tagline, and the
// "lowercase by design" signature line. Server component.
export function Footer() {
  return (
    <footer className="border-t border-border">
      <div className="mx-auto flex max-w-5xl flex-col items-start gap-3 px-6 py-10 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-center gap-2">
          <Link
            href="/"
            className="font-mono text-sm text-ink transition-colors hover:text-lime"
          >
            hermes
          </Link>
          <span className="text-sm text-muted">
            a real assistant, in your chat.
          </span>
        </div>
        <span className="font-mono text-xs text-faint">lowercase by design</span>
      </div>
    </footer>
  );
}
