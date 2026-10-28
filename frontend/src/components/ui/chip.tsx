import * as React from "react";
import { cn } from "@/lib/utils";

export function Chip({
  active,
  className,
  ...props
}: React.ComponentProps<"button"> & { active?: boolean }) {
  return (
    <button
      type="button"
      className={cn(
        "inline-flex h-9 shrink-0 items-center gap-1.5 rounded-full px-4 text-sm font-medium whitespace-nowrap transition-colors",
        active
          ? "bg-foreground text-background"
          : "bg-card text-muted-foreground ring-1 ring-border hover:text-foreground hover:ring-foreground/20",
        className,
      )}
      {...props}
    />
  );
}

export function Tag({ className, ...props }: React.ComponentProps<"span">) {
  return (
    <span
      className={cn("inline-flex items-center rounded-full bg-accent px-2.5 py-0.5 text-xs font-medium text-accent-foreground", className)}
      {...props}
    />
  );
}
