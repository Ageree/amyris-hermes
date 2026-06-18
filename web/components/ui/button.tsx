import { ButtonHTMLAttributes, forwardRef } from "react";
import { cn } from "@/lib/utils";

type Variant = "primary" | "secondary" | "ghost" | "danger";
type Size = "sm" | "md" | "lg";

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
}

// Tactile push: lift on hover, settle on press. Primary carries a soft lime
// glow that intensifies on hover (feedback, motivated motion).
const variants: Record<Variant, string> = {
  primary:
    "bg-lime text-canvas font-medium shadow-[0_1px_0_0_rgba(255,255,255,0.25)_inset,0_8px_24px_-8px_rgba(198,242,78,0.55)] hover:bg-lime-dim hover:shadow-[0_1px_0_0_rgba(255,255,255,0.3)_inset,0_10px_30px_-6px_rgba(198,242,78,0.7)] hover:-translate-y-px active:translate-y-0",
  secondary:
    "bg-surface-2 text-ink border border-border hover:bg-surface-3 hover:border-border-strong hover:-translate-y-px active:translate-y-0",
  ghost: "bg-transparent text-muted hover:text-ink hover:bg-surface-2",
  danger:
    "bg-transparent text-danger border border-border hover:bg-surface-2 hover:border-danger/40",
};

const sizes: Record<Size, string> = {
  sm: "h-8 px-3.5 text-sm",
  md: "h-10 px-5 text-sm",
  lg: "h-12 px-7 text-base",
};

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant = "primary", size = "md", ...props }, ref) => (
    <button
      ref={ref}
      className={cn(
        "inline-flex items-center justify-center gap-2 rounded-[var(--radius)] font-medium",
        "transition-[transform,background-color,box-shadow,border-color,color] duration-200 ease-out",
        "outline-none focus-visible:ring-2 focus-visible:ring-lime focus-visible:ring-offset-2 focus-visible:ring-offset-canvas",
        "disabled:opacity-50 disabled:pointer-events-none",
        variants[variant],
        sizes[size],
        className,
      )}
      {...props}
    />
  ),
);
Button.displayName = "Button";
