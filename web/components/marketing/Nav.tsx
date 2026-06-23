"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import Image from "next/image";
import { Button } from "@/components/ui/button";
import { Wordmark } from "./Wordmark";

// Marketing top bar — single line, 64px. Mascot "dhizume" wordmark (live pulse)
// left; in-page anchors + "sign in" + a single "get started" CTA right. Anchor
// links collapse below md so the bar never wraps.
//
// The fold is the dhizume throne wallpaper — keep it chrome-free: the bar is
// HIDDEN at the very top and slides in once you scroll past ~58% of the first
// screen, then hides again near the top. Detection uses an IntersectionObserver
// on a self-managed sentinel (no scroll listener), so it never re-renders on
// every frame. Reduced-motion just snaps via the transition collapse in CSS.
// Each link wears one of dhizume's poses as its icon — the menu carries the
// mascot, not just text.
const SECTIONS = [
  { href: "#how", label: "how it works", icon: "/dhizume/icons/wave.png" },
  { href: "#pricing", label: "pricing", icon: "/dhizume/icons/point.png" },
  { href: "#faq", label: "faq", icon: "/dhizume/icons/think.png" },
];

export function Nav() {
  const [shown, setShown] = useState(false);

  useEffect(() => {
    // a 1px sentinel ~58% down the first screen; once it scrolls above the
    // viewport the nav appears. IntersectionObserver, not a scroll handler.
    const sentinel = document.createElement("div");
    sentinel.setAttribute("aria-hidden", "true");
    Object.assign(sentinel.style, {
      position: "absolute",
      top: "58vh",
      left: "0",
      width: "1px",
      height: "1px",
      pointerEvents: "none",
    });
    document.body.appendChild(sentinel);
    const io = new IntersectionObserver(
      ([entry]) => setShown(!entry.isIntersecting),
      { threshold: 0 },
    );
    io.observe(sentinel);
    return () => {
      io.disconnect();
      sentinel.remove();
    };
  }, []);

  return (
    <header
      className={`fixed inset-x-0 top-0 z-40 border-b border-border/60 bg-canvas/70 backdrop-blur-xl transition-[transform,opacity] duration-300 ease-out ${
        shown ? "translate-y-0 opacity-100" : "pointer-events-none -translate-y-full opacity-0"
      }`}
    >
      <nav className="mx-auto flex h-16 max-w-6xl items-center justify-between px-6">
        <Wordmark />

        <div className="hidden items-center gap-7 md:flex">
          {SECTIONS.map((s) => (
            <a
              key={s.href}
              href={s.href}
              className="group/link inline-flex items-center gap-2 text-sm text-muted transition-colors hover:text-ink"
            >
              <Image
                src={s.icon}
                alt=""
                width={22}
                height={22}
                className="h-5 w-5 rounded-full object-cover ring-1 ring-border-strong grayscale transition group-hover/link:grayscale-0 group-hover/link:ring-lime/50"
              />
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
