import { ElementType, HTMLAttributes, forwardRef } from "react";
import { cn } from "@/lib/utils";

export function Card({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn(
        "rounded-[var(--radius)] border border-border bg-surface p-6",
        className,
      )}
      {...props}
    />
  );
}

// CardTitle accepts an optional `as` prop so callers can choose the correct
// heading level for their document position (item 5). Default is h3 for
// backwards-compat; under a page h1 pass as="h2".
// forwardRef lets callers focus the heading programmatically (item 1).
interface CardTitleProps extends HTMLAttributes<HTMLHeadingElement> {
  as?: ElementType;
}

export const CardTitle = forwardRef<HTMLHeadingElement, CardTitleProps>(
  function CardTitle({ as: Tag = "h3", className, ...props }, ref) {
    return (
      <Tag
        ref={ref}
        className={cn("text-lg font-medium text-ink", className)}
        {...props}
      />
    );
  },
);

export function CardDescription({
  className,
  ...props
}: HTMLAttributes<HTMLParagraphElement>) {
  return <p className={cn("text-sm text-muted", className)} {...props} />;
}
