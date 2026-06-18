import Link from "next/link";
import { Button } from "@/components/ui/button";
import { Wordmark } from "./Wordmark";

// Marketing top bar — single line, ≤72px. Mono "hermes" wordmark (live pulse)
// left; in-page anchors + "sign in" + a single "get started" CTA right. Server
// component (links only). Anchor links collapse below md so the bar never wraps.
const SECTIONS = [
  { href: "#how", label: "how it works" },
  { href: "#pricing", label: "pricing" },
  { href: "#faq", label: "faq" },
];

export function Nav() {
  return (
    <header className="sticky top-0 z-40 border-b border-border/70 bg-canvas/70 backdrop-blur-xl">
      <nav className="mx-auto flex h-16 max-w-6xl items-center justify-between px-6">
        <Wordmark />

        <div className="hidden items-center gap-7 md:flex">
          {SECTIONS.map((s) => (
            <a
              key={s.href}
              href={s.href}
              className="text-sm text-muted transition-colors hover:text-ink"
            >
              {s.label}
            </a>
          ))}
        </div>

        <div className="flex items-center gap-2 sm:gap-3">
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
