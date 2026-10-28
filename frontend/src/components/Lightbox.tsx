import { useEffect, useRef, useState } from "react";
import { ChevronLeft, ChevronRight, X } from "lucide-react";

/** Просмотр фото на весь экран: стрелки, свайп, Esc. */
export function Lightbox({ photos, start, onClose }: { photos: string[]; start: number; onClose: () => void }) {
  const [index, setIndex] = useState(start);
  const touch = useRef<number | null>(null);
  const go = (d: number) => setIndex((i) => (i + d + photos.length) % photos.length);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
      if (e.key === "ArrowRight") go(1);
      if (e.key === "ArrowLeft") go(-1);
    };
    window.addEventListener("keydown", onKey);
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = prev;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [onClose]);

  const many = photos.length > 1;
  return (
    <div
      className="fixed inset-0 z-[60] flex items-center justify-center bg-black/90 print:hidden"
      role="dialog"
      aria-modal
      onClick={onClose}
      onTouchStart={(e) => (touch.current = e.touches[0].clientX)}
      onTouchEnd={(e) => {
        if (touch.current === null) return;
        const dx = e.changedTouches[0].clientX - touch.current;
        touch.current = null;
        if (Math.abs(dx) > 50 && many) go(dx < 0 ? 1 : -1);
      }}
    >
      <img
        src={photos[index]}
        alt=""
        className="max-h-[100svh] max-w-full object-contain select-none"
        onClick={(e) => {
          e.stopPropagation();
          if (many) go(1);
        }}
      />
      <button
        className="absolute top-[max(1rem,env(safe-area-inset-top))] right-4 flex size-10 items-center justify-center rounded-full bg-white/15 text-white backdrop-blur-md"
        onClick={onClose}
        aria-label="Закрыть"
      >
        <X className="size-5" />
      </button>
      {many && (
        <>
          <button
            className="absolute left-3 hidden size-11 items-center justify-center rounded-full bg-white/15 text-white backdrop-blur-md sm:flex"
            onClick={(e) => {
              e.stopPropagation();
              go(-1);
            }}
            aria-label="Предыдущее фото"
          >
            <ChevronLeft className="size-6" />
          </button>
          <button
            className="absolute right-3 hidden size-11 items-center justify-center rounded-full bg-white/15 text-white backdrop-blur-md sm:flex"
            onClick={(e) => {
              e.stopPropagation();
              go(1);
            }}
            aria-label="Следующее фото"
          >
            <ChevronRight className="size-6" />
          </button>
          <span className="absolute bottom-[max(1rem,env(safe-area-inset-bottom))] rounded-full bg-white/15 px-3 py-1 text-sm text-white tabular-nums backdrop-blur-md">
            {index + 1} / {photos.length}
          </span>
        </>
      )}
    </div>
  );
}
