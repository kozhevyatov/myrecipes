import { useEffect, useState } from "react";
import { Pause, Play, RotateCcw, Timer } from "lucide-react";
import { toast } from "sonner";
import { cn } from "@/lib/utils";

function fmt(sec: number) {
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}

/** Таймер шага: нажал — пошёл отсчёт; по окончании вибрация и уведомление. */
export function StepTimer({ minutes, label }: { minutes: number; label: string }) {
  const total = minutes * 60;
  const [left, setLeft] = useState(total);
  const [running, setRunning] = useState(false);
  const [endsAt, setEndsAt] = useState<number | null>(null);

  useEffect(() => {
    if (!running || endsAt === null) return;
    const tick = () => {
      const rest = Math.max(0, Math.round((endsAt - Date.now()) / 1000));
      setLeft(rest);
      if (rest === 0) {
        setRunning(false);
        setEndsAt(null);
        navigator.vibrate?.([300, 150, 300, 150, 300]);
        toast.success(`Таймер: ${label}`, { description: "Время вышло!", duration: 15000 });
      }
    };
    tick();
    const id = setInterval(tick, 500);
    return () => clearInterval(id);
  }, [running, endsAt, label]);

  const start = () => {
    const from = left === 0 ? total : left;
    setLeft(from);
    setEndsAt(Date.now() + from * 1000);
    setRunning(true);
  };
  const pause = () => {
    setRunning(false);
    setEndsAt(null);
  };
  const reset = () => {
    pause();
    setLeft(total);
  };

  const touched = left !== total || running;

  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full border text-sm font-bold tabular-nums transition-colors",
        running ? "border-primary bg-primary text-primary-foreground" : "bg-card",
      )}
    >
      <button
        type="button"
        onClick={running ? pause : start}
        className="flex items-center gap-1.5 py-1.5 pr-1 pl-3"
        aria-label={running ? "Пауза" : "Запустить таймер"}
      >
        {running ? <Pause className="size-3.5" /> : touched ? <Play className="size-3.5" /> : <Timer className="size-3.5" />}
        {touched ? fmt(left) : `${minutes} мин`}
      </button>
      {touched && !running ? (
        <button type="button" onClick={reset} className="py-1.5 pr-3 pl-1" aria-label="Сбросить">
          <RotateCcw className="size-3.5" />
        </button>
      ) : (
        <span className="w-2" />
      )}
    </span>
  );
}
