import { cn } from "@/lib/utils";

/** Знак: миска с паром. */
export function Logo({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" className={cn("size-8", className)} aria-hidden>
      <rect width="32" height="32" rx="10" className="fill-primary" />
      <path d="M7.5 16.5h17a8.5 8.5 0 0 1-17 0Z" className="fill-primary-foreground" />
      <path
        d="M12 12.5c0-1.8 1.8-1.8 1.8-3.6M16 12.5c0-1.8 1.8-1.8 1.8-3.6M20 12.5c0-1.8 1.8-1.8 1.8-3.6"
        className="stroke-primary-foreground"
        strokeWidth="1.6"
        strokeLinecap="round"
        fill="none"
      />
    </svg>
  );
}

export function Brand({ name }: { name: string }) {
  return (
    <span className="flex items-center gap-2.5">
      <Logo />
      <span className="font-display text-[17px] font-semibold tracking-[-0.03em]">{name}</span>
    </span>
  );
}
