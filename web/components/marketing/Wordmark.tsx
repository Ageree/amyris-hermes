import Link from "next/link";
import Image from "next/image";
import { cn } from "@/lib/utils";

// The "dhizume" wordmark: the mascot's masked-muse avatar in a soft ring, with a
// living rose dot (the "it's alive" signal the whole brand leans on), then the
// lowercase mono name. Replaces the old bare-dot hermes mark.
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
        "group inline-flex items-center gap-2.5 font-mono text-lg tracking-tight text-lime transition-colors hover:text-lime-dim",
        className,
      )}
    >
      <span className="relative inline-flex h-7 w-7 shrink-0">
        <Image
          src="/dhizume/avatar.png"
          alt=""
          width={28}
          height={28}
          priority
          className="h-7 w-7 rounded-full object-cover ring-1 ring-border-strong"
        />
        {/* living rose dot — pulses to signal the assistant is online */}
        <span aria-hidden className="absolute -bottom-0.5 -right-0.5 inline-flex h-2.5 w-2.5 items-center justify-center">
          <span className="absolute inline-block h-2.5 w-2.5 rounded-full bg-lime/60 ping-ring" />
          <span className="relative inline-block h-2 w-2 rounded-full bg-lime ring-2 ring-canvas pulse-dot" />
        </span>
      </span>
      dhizume
    </Link>
  );
}
