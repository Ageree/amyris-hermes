import { AnchorHTMLAttributes, forwardRef } from "react";
import { cn } from "@/lib/utils";

export interface HoverButtonProps extends AnchorHTMLAttributes<HTMLAnchorElement> {}

export const HoverButton = forwardRef<HTMLAnchorElement, HoverButtonProps>(
  ({ className, children, ...props }, ref) => (
    <a
      ref={ref}
      className={cn(
        "group relative inline-flex h-[3.625rem] min-w-52 items-center justify-center gap-5 overflow-hidden border border-[rgba(31,35,34,0.28)] bg-[rgba(246,244,235,0.82)] px-8 text-xl font-semibold text-[#171b1c] shadow-[0_1px_0_rgba(255,255,255,0.46)_inset]",
        "transition-[transform,border-color,box-shadow,background-color] duration-300 ease-out hover:-translate-y-px hover:border-[rgba(31,35,34,0.22)] hover:shadow-[0_1px_0_rgba(255,255,255,0.42)_inset,0_16px_34px_-22px_rgba(45,53,45,0.55)] active:translate-y-0",
        "outline-none focus-visible:ring-2 focus-visible:ring-ink/45 focus-visible:ring-offset-2 focus-visible:ring-offset-canvas",
        className,
      )}
      {...props}
    >
      <span
        aria-hidden
        className="absolute inset-0 bg-[linear-gradient(100deg,rgba(208,229,230,0.82),rgba(220,203,232,0.9))] opacity-0 transition-opacity duration-300 ease-out group-hover:opacity-100"
      />
      <span
        aria-hidden
        className="absolute inset-0 bg-[radial-gradient(circle_at_16px_18px,rgba(21,31,30,0.13)_0_1px,transparent_1.6px)] bg-[length:22px_22px] opacity-0 transition-opacity duration-300 ease-out group-hover:opacity-100"
      />
      <span className="relative z-10">{children}</span>
      <span
        aria-hidden="true"
        className="relative z-10 text-[1.8rem] font-medium leading-none transition-transform duration-300 ease-out group-hover:translate-x-1"
      >
        →
      </span>
    </a>
  ),
);
HoverButton.displayName = "HoverButton";
