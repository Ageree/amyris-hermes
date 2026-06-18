"use client";

import { useEffect } from "react";

// Reveals .reveal elements once, the moment they enter the viewport, then stops
// observing them (reveal-once-and-stay). Falls back to showing everything when
// IntersectionObserver is missing or the user prefers reduced motion. Re-scans
// on client navigations via a MutationObserver so wizard/dashboard reveals work.
export function RevealObserver() {
  useEffect(() => {
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const showAll = () =>
      document
        .querySelectorAll(".reveal:not(.reveal-in)")
        .forEach((el) => el.classList.add("reveal-in"));

    if (reduce || !("IntersectionObserver" in window)) {
      showAll();
      return;
    }

    const io = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) {
            entry.target.classList.add("reveal-in");
            io.unobserve(entry.target);
          }
        }
      },
      { rootMargin: "0px 0px -8% 0px", threshold: 0.12 },
    );

    const observeAll = () =>
      document
        .querySelectorAll(".reveal:not(.reveal-in)")
        .forEach((el) => io.observe(el));

    observeAll();

    // catch reveal nodes added by client-side navigation
    const mo = new MutationObserver(() => observeAll());
    mo.observe(document.body, { childList: true, subtree: true });

    return () => {
      io.disconnect();
      mo.disconnect();
    };
  }, []);

  return null;
}
