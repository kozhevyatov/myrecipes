import { cn } from "@/lib/utils";

// Несколько спокойных оттенков для «буквенных» аватаров — один и тот же человек всегда одного цвета
const TINTS = [
  "bg-[oklch(0.92_0.04_45)] text-[oklch(0.42_0.1_40)]",
  "bg-[oklch(0.9_0.06_82)] text-[oklch(0.38_0.08_70)]",
  "bg-[oklch(0.9_0.05_250)] text-[oklch(0.38_0.08_250)]",
  "bg-[oklch(0.9_0.05_20)] text-[oklch(0.42_0.1_25)]",
  "bg-[oklch(0.9_0.05_310)] text-[oklch(0.4_0.08_310)]",
];

function initials(name: string) {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "?";
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[1][0]).toUpperCase();
}

function tint(seed: string) {
  let h = 0;
  for (const ch of seed) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  return TINTS[h % TINTS.length];
}

/** Круглый аватар: фото или инициалы. */
export function Avatar({
  src,
  name,
  className,
}: {
  src?: string | null;
  name: string;
  className?: string;
}) {
  return (
    <span
      className={cn(
        "relative inline-flex size-9 shrink-0 items-center justify-center overflow-hidden rounded-full text-[13px] font-semibold select-none",
        !src && tint(name),
        className,
      )}
      aria-hidden
    >
      {src ? <img src={src} alt="" className="h-full w-full object-cover" /> : <span>{initials(name)}</span>}
    </span>
  );
}
