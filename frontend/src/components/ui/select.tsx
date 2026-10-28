import * as React from "react";
import { ChevronDown } from "lucide-react";
import { cn } from "@/lib/utils";

/** Нативный select в стиле полей ввода — на телефоне открывается системным списком. */
export function Select({ className, children, ...props }: React.ComponentProps<"select">) {
  return (
    <div className="relative">
      <select
        className={cn(
          "flex h-11 w-full appearance-none rounded-xl border border-input bg-card pr-9 pl-3.5 text-[15px] transition-colors outline-none",
          "focus-visible:border-primary focus-visible:ring-4 focus-visible:ring-ring/30 disabled:opacity-50",
          className,
        )}
        {...props}
      >
        {children}
      </select>
      <ChevronDown className="pointer-events-none absolute top-1/2 right-3 size-4 -translate-y-1/2 text-muted-foreground" />
    </div>
  );
}
