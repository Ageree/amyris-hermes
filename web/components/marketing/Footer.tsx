import Link from "next/link";
import { Wordmark } from "./Wordmark";

// Restrained footer: live wordmark + tagline, a small link cluster, and the
// "lowercase by design" signature. Server component.
export function Footer() {
  return (
    <footer className="border-t border-border">
      <div className="mx-auto flex max-w-6xl flex-col gap-8 px-6 py-12 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex flex-col gap-2">
          <Wordmark />
          <span className="text-sm text-muted">a real assistant, in your chat.</span>
        </div>

        <nav className="flex flex-wrap items-center gap-x-6 gap-y-2 text-sm text-muted">
          <a href="#how" className="transition-colors hover:text-ink">how it works</a>
          <a href="#pricing" className="transition-colors hover:text-ink">pricing</a>
          <a href="#faq" className="transition-colors hover:text-ink">faq</a>
          <Link href="/signin" className="transition-colors hover:text-ink">sign in</Link>
        </nav>

        <span className="font-mono text-xs text-faint">lowercase by design</span>
      </div>
    </footer>
  );
}
