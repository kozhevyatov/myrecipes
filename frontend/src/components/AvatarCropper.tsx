import { useCallback, useEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import { Loader2, Minus, Plus, X } from "lucide-react";
import { Button } from "@/components/ui/button";

const OUTPUT = 512; // сервер ужмёт до 256 — запас для чёткости
const MAX_ZOOM = 4;

type Props = { file: File; onCancel: () => void; onDone: (blob: Blob) => void | Promise<void> };

/**
 * Кадрирование аватара в квадрат без сторонних библиотек.
 * Двигать — пальцем/мышью, масштаб — ползунок, колёсико или щипок двумя пальцами.
 * Круг показывает, как аватар будет выглядеть на сайте.
 */
export function AvatarCropper({ file, onCancel, onDone }: Props) {
  const [img, setImg] = useState<HTMLImageElement | null>(null);
  const [view, setView] = useState(300);
  const [zoom, setZoom] = useState(1);
  const [pos, setPos] = useState({ x: 0, y: 0 });
  const [saving, setSaving] = useState(false);
  const pointers = useRef(new Map<number, { x: number; y: number }>());
  const pinch = useRef<{ dist: number; zoom: number } | null>(null);

  // Загрузка картинки
  useEffect(() => {
    const url = URL.createObjectURL(file);
    const image = new Image();
    image.onload = () => setImg(image);
    image.src = url;
    return () => URL.revokeObjectURL(url);
  }, [file]);

  // Размер окна кадрирования под ширину экрана
  useEffect(() => {
    const fit = () => setView(Math.min(320, window.innerWidth - 64));
    fit();
    window.addEventListener("resize", fit);
    return () => window.removeEventListener("resize", fit);
  }, []);

  const baseScale = img ? view / Math.min(img.naturalWidth, img.naturalHeight) : 1;
  const scale = baseScale * zoom;

  const clamp = useCallback(
    (p: { x: number; y: number }, s = scale) => {
      if (!img) return p;
      const w = img.naturalWidth * s;
      const h = img.naturalHeight * s;
      return {
        x: Math.min(0, Math.max(view - w, p.x)),
        y: Math.min(0, Math.max(view - h, p.y)),
      };
    },
    [img, scale, view],
  );

  // Начальное положение — по центру
  useEffect(() => {
    if (!img) return;
    const s = view / Math.min(img.naturalWidth, img.naturalHeight);
    setZoom(1);
    setPos({ x: (view - img.naturalWidth * s) / 2, y: (view - img.naturalHeight * s) / 2 });
  }, [img, view]);

  // Масштаб относительно центра окна — картинка не «уезжает»
  const applyZoom = useCallback(
    (next: number) => {
      if (!img) return;
      const z = Math.min(MAX_ZOOM, Math.max(1, next));
      const oldS = baseScale * zoom;
      const newS = baseScale * z;
      const c = view / 2;
      setPos(clamp({ x: c - ((c - pos.x) / oldS) * newS, y: c - ((c - pos.y) / oldS) * newS }, newS));
      setZoom(z);
    },
    [img, baseScale, zoom, view, pos, clamp],
  );

  const onDown = (e: ReactPointerEvent) => {
    (e.target as Element).setPointerCapture(e.pointerId);
    pointers.current.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (pointers.current.size === 2) {
      const [a, b] = [...pointers.current.values()];
      pinch.current = { dist: Math.hypot(a.x - b.x, a.y - b.y), zoom };
    }
  };
  const onMove = (e: ReactPointerEvent) => {
    const prev = pointers.current.get(e.pointerId);
    if (!prev) return;
    pointers.current.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (pointers.current.size === 2 && pinch.current) {
      const [a, b] = [...pointers.current.values()];
      applyZoom(pinch.current.zoom * (Math.hypot(a.x - b.x, a.y - b.y) / pinch.current.dist));
      return;
    }
    setPos((p) => clamp({ x: p.x + e.clientX - prev.x, y: p.y + e.clientY - prev.y }));
  };
  const onUp = (e: ReactPointerEvent) => {
    pointers.current.delete(e.pointerId);
    if (pointers.current.size < 2) pinch.current = null;
  };

  async function save() {
    if (!img) return;
    setSaving(true);
    try {
      const canvas = document.createElement("canvas");
      canvas.width = OUTPUT;
      canvas.height = OUTPUT;
      const ctx = canvas.getContext("2d")!;
      ctx.imageSmoothingQuality = "high";
      const size = view / scale;
      ctx.drawImage(img, -pos.x / scale, -pos.y / scale, size, size, 0, 0, OUTPUT, OUTPUT);
      const blob = await new Promise<Blob | null>((r) => canvas.toBlob(r, "image/jpeg", 0.92));
      if (blob) await onDone(blob);
    } finally {
      setSaving(false);
    }
  }

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onCancel();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onCancel]);

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/50 p-0 backdrop-blur-sm sm:items-center sm:p-4" role="dialog" aria-modal>
      <div className="w-full max-w-md rounded-t-3xl border bg-card p-6 pb-[max(1.5rem,env(safe-area-inset-bottom))] shadow-xl sm:rounded-3xl">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-semibold">Фото профиля</h2>
          <Button variant="ghost" size="icon" onClick={onCancel} aria-label="Закрыть">
            <X />
          </Button>
        </div>
        <p className="mt-1 text-sm text-muted-foreground">Перетащите фото и выберите масштаб.</p>

        <div className="mt-5 flex justify-center">
          <div
            className="relative cursor-grab touch-none overflow-hidden rounded-2xl bg-muted active:cursor-grabbing"
            style={{ width: view, height: view }}
            onPointerDown={onDown}
            onPointerMove={onMove}
            onPointerUp={onUp}
            onPointerCancel={onUp}
            onWheel={(e) => applyZoom(zoom * (e.deltaY < 0 ? 1.08 : 1 / 1.08))}
          >
            {img ? (
              <img
                src={img.src}
                alt=""
                draggable={false}
                className="pointer-events-none absolute top-0 left-0 max-w-none origin-top-left select-none"
                style={{ transform: `translate(${pos.x}px, ${pos.y}px) scale(${scale})` }}
              />
            ) : (
              <div className="flex h-full items-center justify-center">
                <Loader2 className="size-6 animate-spin text-muted-foreground" />
              </div>
            )}
            {/* Затемнение вокруг круга */}
            <div className="pointer-events-none absolute inset-0 rounded-full shadow-[0_0_0_9999px_rgb(0_0_0/0.45)] ring-2 ring-white/80" />
          </div>
        </div>

        <div className="mt-5 flex items-center gap-3">
          <Button variant="ghost" size="icon" aria-label="Уменьшить" onClick={() => applyZoom(zoom - 0.25)} disabled={zoom <= 1}>
            <Minus />
          </Button>
          <input
            type="range"
            min={1}
            max={MAX_ZOOM}
            step={0.01}
            value={zoom}
            onChange={(e) => applyZoom(Number(e.target.value))}
            className="h-1.5 flex-1 cursor-pointer accent-primary"
            aria-label="Масштаб"
          />
          <Button variant="ghost" size="icon" aria-label="Увеличить" onClick={() => applyZoom(zoom + 0.25)} disabled={zoom >= MAX_ZOOM}>
            <Plus />
          </Button>
        </div>

        <div className="mt-6 flex justify-end gap-2">
          <Button variant="ghost" onClick={onCancel}>
            Отмена
          </Button>
          <Button onClick={save} disabled={!img || saving}>
            {saving && <Loader2 className="animate-spin" />} Сохранить
          </Button>
        </div>
      </div>
    </div>
  );
}
