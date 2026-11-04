import { useEffect, useRef, useState } from "react";
import { Check, Moon, Palette, Sun } from "lucide-react";
import { Button } from "@/components/ui/button";
import { THEMES, useTheme } from "@/lib/theme";
import { cn } from "@/lib/utils";

/** Кружок-образец темы: фон + акцентная точка */
function Swatch({ bg, accent }: { bg: string; accent: string }) {
  return (
    <span
      className="relative grid size-7 shrink-0 place-items-center rounded-full border border-black/10 dark:border-white/15"
      style={{ background: bg }}
    >
      <span className="size-3 rounded-full" style={{ background: accent }} />
    </span>
  );
}

/** Выбор темы оформления в шапке */
export function ThemeMenu() {
  const { theme, setTheme } = useTheme();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: PointerEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("pointerdown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const groups = [
    { title: "Светлые", icon: Sun, items: THEMES.filter((t) => !t.dark) },
    { title: "Тёмные", icon: Moon, items: THEMES.filter((t) => t.dark) },
  ];

  return (
    <div ref={ref} className="relative">
      <Button
        variant="ghost"
        size="icon"
        onClick={() => setOpen((v) => !v)}
        aria-label="Тема оформления"
        aria-haspopup="menu"
        aria-expanded={open}
        title="Тема оформления"
      >
        <Palette />
      </Button>
      {open && (
        <div
          role="menu"
          className="absolute top-full right-0 z-50 mt-2 w-60 rounded-2xl border bg-card p-1.5 text-card-foreground shadow-xl shadow-black/10"
        >
          {groups.map(({ title, icon: Icon, items }) => (
            <div key={title} className="py-1">
              <div className="flex items-center gap-1.5 px-2.5 pt-1 pb-1.5 text-[11px] font-medium tracking-wide text-muted-foreground uppercase">
                <Icon className="size-3.5" /> {title}
              </div>
              {items.map((t) => (
                <button
                  key={t.id}
                  role="menuitemradio"
                  aria-checked={theme === t.id}
                  className={cn(
                    "flex w-full items-center gap-3 rounded-xl px-2.5 py-2 text-left text-sm transition-colors hover:bg-muted",
                    theme === t.id && "bg-muted",
                  )}
                  onClick={() => {
                    setTheme(t.id);
                    setOpen(false);
                  }}
                >
                  <Swatch bg={t.bg} accent={t.accent} />
                  <span className="min-w-0 flex-1">
                    <span className="block font-medium">{t.label}</span>
                    <span className="block text-xs text-muted-foreground">{t.hint}</span>
                  </span>
                  {theme === t.id && <Check className="size-4 text-primary" />}
                </button>
              ))}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
