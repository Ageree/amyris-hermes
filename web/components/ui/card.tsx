import { ElementType, HTMLAttributes, forwardRef } from "react";
import { cn } from "@/lib/utils";

// Base surface card. A 1px inner top-highlight gives a hint of physical edge
// (depth without a heavy black drop shadow). Callers add hover lift where wanted.
export function Card({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn(
        "rounded-[var(--radius-lg)] border border-border bg-surface p-6",
        "shadow-[0_1px_0_0_rgba(255,255,255,0.04)_inset]",
        className,
      )}
      {...props}
    />
  );
}

// CardTitle accepts `as` so callers pick the correct heading level for their
// document position. Default h3 (back-compat); under a page h1 pass as="h2".
// forwardRef lets callers focus the heading programmatically.
interface CardTitleProps extends HTMLAttributes<HTMLHeadingElement> {
  as?: ElementType;
}

export const CardTitle = forwardRef<HTMLHeadingElement, CardTitleProps>(
  function CardTitle({ as: Tag = "h3", className, ...props }, ref) {
    return (
      <Tag
        ref={ref}
        className={cn(
          "text-lg font-medium tracking-tight text-ink",
          className,
        )}
        {...props}
      />
    );
  },
);

export function CardDescription({
  className,
  ...props
}: HTMLAttributes<HTMLParagraphElement>) {
  return (
    <p
      className={cn("text-sm leading-relaxed text-muted", className)}
      {...props}
    />
  );
}
