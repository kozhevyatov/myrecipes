import { useState } from "react";
import { useNavigate } from "react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CalendarPlus, Loader2, Minus, Plus } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Chip } from "@/components/ui/chip";
import { Sheet } from "@/components/ui/sheet";
import { api, type MealSlot } from "@/lib/api";
import { SLOTS, WEEKDAYS, addDays, dayLabel, iso, relativeDay } from "@/lib/dates";
import { plural } from "@/lib/format";

/** «В меню»: выбрать день, приём пищи и порции. */
export function AddToPlanSheet({
  recipe,
  onClose,
}: {
  recipe: { id: number; title: string; servings: number };
  onClose: () => void;
}) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const today = new Date();
  const days = Array.from({ length: 14 }, (_, i) => addDays(today, i));
  const [day, setDay] = useState(iso(today));
  const [slot, setSlot] = useState<MealSlot>("dinner");
  const [servings, setServings] = useState(recipe.servings);
  const owners = useQuery({ queryKey: ["plan-owners"], queryFn: api.plan.owners });
  const [owner, setOwner] = useState<number | undefined>(undefined);

  const add = useMutation({
    mutationFn: () => api.plan.add({ day, slot, recipe_id: recipe.id, servings, owner_id: owner }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["plan"] });
      const d = days.find((x) => iso(x) === day)!;
      toast.success("В меню", {
        description: `${relativeDay(d) ?? dayLabel(d)}, ${SLOTS.find((s) => s.id === slot)!.label.toLowerCase()}`,
        action: { label: "Открыть", onClick: () => navigate(`/plan?date=${day}${owner ? `&owner=${owner}` : ""}`) },
      });
      onClose();
    },
    onError: (e) => toast.error(e.message),
  });

  return (
    <Sheet
      title="В меню"
      onClose={onClose}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Отмена
          </Button>
          <Button onClick={() => add.mutate()} disabled={add.isPending}>
            {add.isPending ? <Loader2 className="animate-spin" /> : <CalendarPlus />} Добавить
          </Button>
        </>
      }
    >
      <p className="truncate text-sm text-muted-foreground">{recipe.title}</p>

      {owners.data && owners.data.owners.length > 1 && (
        <div className="mt-4">
          <p className="mb-2 text-sm font-semibold">Чьё меню</p>
          <div className="flex flex-wrap gap-2">
            {owners.data.owners.map((o, i) => (
              <Chip key={o.id} active={(owner ?? owners.data.owners[0].id) === o.id} onClick={() => setOwner(i === 0 ? undefined : o.id)}>
                {i === 0 ? "Моё" : o.name}
              </Chip>
            ))}
          </div>
        </div>
      )}

      <p className="mt-4 mb-2 text-sm font-semibold">День</p>
      <div className="-mx-6 flex gap-2 overflow-x-auto px-6 pb-1 [scrollbar-width:none]">
        {days.map((d) => {
          const v = iso(d);
          const on = v === day;
          return (
            <button
              key={v}
              type="button"
              onClick={() => setDay(v)}
              className={
                on
                  ? "flex w-14 shrink-0 flex-col items-center rounded-2xl bg-foreground py-2 text-background"
                  : "flex w-14 shrink-0 flex-col items-center rounded-2xl bg-muted py-2 text-muted-foreground hover:text-foreground"
              }
            >
              <span className="text-xs">{relativeDay(d) === "Сегодня" ? "сег." : WEEKDAYS[(d.getDay() + 6) % 7]}</span>
              <span className="text-lg font-semibold tabular-nums">{d.getDate()}</span>
            </button>
          );
        })}
      </div>

      <p className="mt-4 mb-2 text-sm font-semibold">Когда</p>
      <div className="flex flex-wrap gap-2">
        {SLOTS.map((s) => (
          <Chip key={s.id} active={slot === s.id} onClick={() => setSlot(s.id)}>
            {s.label}
          </Chip>
        ))}
      </div>

      <div className="mt-4 flex items-center justify-between">
        <p className="text-sm font-semibold">Порций</p>
        <div className="flex items-center gap-1 rounded-full bg-muted p-1">
          <button
            className="flex size-8 items-center justify-center rounded-full hover:bg-card disabled:opacity-40"
            onClick={() => setServings((s) => Math.max(1, s - 1))}
            disabled={servings <= 1}
            aria-label="Меньше порций"
          >
            <Minus className="size-4" />
          </button>
          <span className="min-w-[4.5rem] text-center text-sm font-bold tabular-nums">
            {servings} {plural(servings, "порция", "порции", "порций")}
          </span>
          <button
            className="flex size-8 items-center justify-center rounded-full hover:bg-card"
            onClick={() => setServings((s) => Math.min(100, s + 1))}
            aria-label="Больше порций"
          >
            <Plus className="size-4" />
          </button>
        </div>
      </div>
    </Sheet>
  );
}
