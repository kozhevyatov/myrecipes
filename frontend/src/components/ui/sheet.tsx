import { useEffect, type ReactNode } from "react";
import { X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

/** Окно поверх страницы: на телефоне — снизу, на компьютере — по центру. */
export function Sheet({
  title,
  onClose,
  children,
  footer,
  className,
}: {
  title: ReactNode;
  onClose: () => void;
  children: ReactNode;
  footer?: ReactNode;
  className?: string;
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = prev;
    };
  }, [onClose]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-end justify-center bg-black/45 backdrop-blur-sm sm:items-center sm:p-4 print:hidden"
      role="dialog"
      aria-modal
      onClick={onClose}
    >
      <div
        className={cn(
          "flex max-h-[92svh] w-full max-w-md flex-col rounded-t-3xl border bg-card shadow-xl sm:rounded-3xl",
          className,
        )}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between gap-3 px-6 pt-5">
          <h2 className="min-w-0 truncate text-lg font-semibold">{title}</h2>
          <Button variant="ghost" size="icon" className="-mr-2 shrink-0" onClick={onClose} aria-label="Закрыть">
            <X />
          </Button>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto px-6 pt-2 pb-5">{children}</div>
        {footer && (
          <div className="flex justify-end gap-2 border-t px-6 pt-4 pb-[max(1rem,env(safe-area-inset-bottom))]">{footer}</div>
        )}
      </div>
    </div>
  );
}
