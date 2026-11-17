import { useEffect, useState } from "react";
import { ArrowUp } from "lucide-react";
import { Button } from "@/components/ui/button";

export function BackToTop() {
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    const updateVisibility = () => setVisible(window.scrollY > 400);
    updateVisibility();
    window.addEventListener("scroll", updateVisibility, { passive: true });
    window.addEventListener("pageshow", updateVisibility);
    return () => {
      window.removeEventListener("scroll", updateVisibility);
      window.removeEventListener("pageshow", updateVisibility);
    };
  }, []);

  if (!visible) return null;

  return (
    <Button
      type="button"
      aria-label="Вернуться к началу страницы"
      className="fixed right-4 bottom-[calc(5rem+env(safe-area-inset-bottom))] z-20 shadow-lg print:hidden sm:right-6 lg:bottom-6"
      onClick={() => window.scrollTo({
        top: 0,
        behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth",
      })}
    >
      <ArrowUp aria-hidden="true" /> Наверх
    </Button>
  );
}
