import Link from "next/link";
import { cn } from "@/lib/utils";

// The "hermes" wordmark with a living lime dot: a steady core + a radiating ring
// (the "it's alive" signal that the whole brand leans on). Mono, lowercase.
export function Wordmark({
  className,
  href = "/",
}: {
  className?: string;
  href?: string;
}) {
  return (
    <Link
      href={href}
      className={cn(
        "group inline-flex items-center gap-2.5 font-mono text-lg tracking-tight text-ink transition-colors hover:text-lime",
        className,
      )}
    >
      <span aria-hidden className="relative inline-flex h-2.5 w-2.5 items-center justify-center">
        <span className="absolute inline-block h-2.5 w-2.5 rounded-full bg-lime/60 ping-ring" />
        <span className="relative inline-block h-2 w-2 rounded-full bg-lime pulse-dot" />
      </span>
      hermes
    </Link>
  );
}
