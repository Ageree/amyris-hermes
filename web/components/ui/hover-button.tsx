import { AnchorHTMLAttributes, forwardRef } from "react";
import { cn } from "@/lib/utils";

export interface HoverButtonProps extends AnchorHTMLAttributes<HTMLAnchorElement> {}

export const HoverButton = forwardRef<HTMLAnchorElement, HoverButtonProps>(
  ({ className, children, ...props }, ref) => (
    <a
      ref={ref}
      className={cn(
        "group relative inline-flex h-[3.25rem] min-w-40 items-center justify-center overflow-hidden rounded-[var(--radius)] px-7 text-base font-semibold text-canvas",
        "bg-lime shadow-[0_1px_0_rgba(255,255,255,0.62)_inset,0_16px_34px_-16px_rgba(201,255,69,0.84)]",
        "transition-[transform,box-shadow,background-color] duration-300 ease-out hover:-translate-y-px hover:bg-lime-dim hover:shadow-[0_1px_0_rgba(255,255,255,0.62)_inset,0_18px_44px_-14px_rgba(201,255,69,0.95)] active:translate-y-0",
        "outline-none focus-visible:ring-2 focus-visible:ring-lime focus-visible:ring-offset-2 focus-visible:ring-offset-canvas",
        className,
      )}
      {...props}
    >
      <span
        aria-hidden
        className="absolute inset-y-0 -left-1/2 w-1/2 skew-x-[-18deg] bg-white/35 opacity-0 blur-sm transition-[left,opacity] duration-500 ease-out group-hover:left-[120%] group-hover:opacity-100"
      />
      <span className="relative z-10">{children}</span>
    </a>
  ),
);
HoverButton.displayName = "HoverButton";
