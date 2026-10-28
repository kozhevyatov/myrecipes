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
        "inline-flex h-9 shrink-0 items-center gap-1.5 rounded-full border px-3.5 text-sm font-semibold whitespace-nowrap transition-colors",
        active
          ? "border-primary bg-primary text-primary-foreground"
          : "bg-card text-muted-foreground hover:border-primary/40 hover:text-foreground",
        className,
      )}
      {...props}
    />
  );
}

export function Tag({ className, ...props }: React.ComponentProps<"span">) {
  return (
    <span
      className={cn("inline-flex items-center rounded-md bg-accent px-2 py-0.5 text-xs font-semibold text-accent-foreground", className)}
      {...props}
    />
  );
}
