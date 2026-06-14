import Link from "next/link";
import { Button } from "@/components/ui/button";

// Marketing top bar — mono "hermes" wordmark left; "sign in" link + "get started"
// CTA right. Purely a server component (links only, no client state).
export function Nav() {
  return (
    <header className="sticky top-0 z-40 border-b border-border bg-canvas/80 backdrop-blur">
      <nav className="mx-auto flex h-16 max-w-5xl items-center justify-between px-6">
        <Link
          href="/"
          className="flex items-center gap-2 font-mono text-lg tracking-tight text-ink transition-colors hover:text-lime"
        >
          <span
            aria-hidden
            className="inline-block h-2 w-2 rounded-full bg-lime pulse-dot"
          />
          hermes
        </Link>

        <div className="flex items-center gap-2 sm:gap-4">
          <Link
            href="/signin"
            className="px-2 text-sm text-muted transition-colors hover:text-ink"
          >
            sign in
          </Link>
          <Link href="/signin">
            <Button variant="primary" size="sm">
              get started
            </Button>
          </Link>
        </div>
      </nav>
    </header>
  );
}
