import { useCallback, useEffect, useRef, useState } from "react";
import { useParams, useSearchParams } from "react-router";
import { useBackToRecipe } from "@/lib/nav";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, ArrowRight, Check, ListChecks, Loader2, PartyPopper, Sun, X } from "lucide-react";
import { StepTimer } from "@/components/StepTimer";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import { formatAmount, plural } from "@/lib/format";
import { useWakeLock } from "@/lib/useWakeLock";
import { cn } from "@/lib/utils";

/**
 * Режим готовки: один шаг на экран, крупный шрифт, свайпы и стрелки,
 * экран не гаснет. Количество порций передаётся из карточки рецепта (?servings=).
 */
export default function CookPage() {
  const { id } = useParams();
  const recipeId = Number(id);
  const back = useBackToRecipe(recipeId);
  const [params] = useSearchParams();
  const { data: recipe, isLoading } = useQuery({
    queryKey: ["recipe", recipeId],
    queryFn: () => api.recipes.get(recipeId),
  });
  const wake = useWakeLock({ force: true });

  const [index, setIndex] = useState(0); // steps.length — экран «Готово»
  const [showIngredients, setShowIngredients] = useState(false);
  const [checked, setChecked] = useState<Set<number>>(new Set());
  const touch = useRef<{ x: number; y: number } | null>(null);

  const stepsCount = recipe?.steps.length ?? 0;
  const servings = Math.max(1, Number(params.get("servings")) || recipe?.servings || 1);
  const factor = recipe ? servings / recipe.servings : 1;

  const go = useCallback(
    (delta: number) => setIndex((i) => Math.min(Math.max(0, i + delta), stepsCount)),
    [stepsCount],
  );

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "ArrowRight" || e.key === " ") go(1);
      else if (e.key === "ArrowLeft") go(-1);
      else if (e.key === "Escape") back();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [go, back]);

  useEffect(() => {
    if (recipe) document.title = `Готовим: ${recipe.title}`;
  }, [recipe]);

  if (isLoading || !recipe) {
    return (
      <div className="flex min-h-svh items-center justify-center">
        {isLoading ? <Loader2 className="size-6 animate-spin text-muted-foreground" /> : <p>Рецепт не найден</p>}
      </div>
    );
  }

  const finished = index >= stepsCount;
  const step = recipe.steps[index];
  const progress = stepsCount ? Math.min(index, stepsCount) / stepsCount : 1;

  return (
    <div
      className="fixed inset-0 z-50 flex flex-col bg-background"
      onTouchStart={(e) => (touch.current = { x: e.touches[0].clientX, y: e.touches[0].clientY })}
      onTouchEnd={(e) => {
        if (!touch.current || showIngredients) return;
        const dx = e.changedTouches[0].clientX - touch.current.x;
        const dy = e.changedTouches[0].clientY - touch.current.y;
        touch.current = null;
        if (Math.abs(dx) > 60 && Math.abs(dx) > Math.abs(dy) * 1.5) go(dx < 0 ? 1 : -1);
      }}
    >
      {/* Верхняя панель */}
      <header className="flex items-center gap-2 border-b px-3 py-2 pt-[max(0.5rem,env(safe-area-inset-top))]">
        <Button variant="ghost" size="icon" aria-label="Выйти из режима готовки" onClick={back}>
          <X />
        </Button>
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-bold">{recipe.title}</p>
          <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
            {finished ? "Готово" : `Шаг ${index + 1} из ${stepsCount}`}
            {wake.active && (
              <span className="flex items-center gap-1 text-primary">
                · <Sun className="size-3" /> экран не гаснет
              </span>
            )}
          </p>
        </div>
        <Button variant={showIngredients ? "secondary" : "outline"} size="sm" onClick={() => setShowIngredients((v) => !v)}>
          <ListChecks /> <span className="hidden sm:inline">Ингредиенты</span>
        </Button>
      </header>
      <div className="h-1 bg-muted">
        <div className="h-full bg-primary transition-all duration-300" style={{ width: `${progress * 100}%` }} />
      </div>

      {/* Основная часть */}
      <main className="relative flex-1 overflow-y-auto">
        {finished ? (
          <div className="flex h-full flex-col items-center justify-center gap-4 p-8 text-center">
            <div className="rounded-3xl bg-accent p-5">
              <PartyPopper className="size-10 text-primary" />
            </div>
            <h1 className="title-display text-3xl">Приятного аппетита!</h1>
            <p className="text-muted-foreground">Все шаги пройдены.</p>
            <div className="mt-2 flex gap-3">
              <Button variant="outline" onClick={() => setIndex(0)}>
                С начала
              </Button>
              <Button onClick={back}>К рецепту</Button>
            </div>
          </div>
        ) : (
          <div className="mx-auto flex min-h-full max-w-3xl flex-col justify-center gap-8 px-6 py-10 sm:px-10">
            <span className="title-display flex size-14 items-center justify-center rounded-full bg-accent text-2xl text-accent-foreground">
              {index + 1}
            </span>
            <p className="text-2xl leading-snug font-semibold whitespace-pre-line sm:text-3xl sm:leading-snug">
              {step.text}
            </p>
            {step.image_url && (
              <img
                src={step.image_url}
                alt=""
                className="max-h-[40svh] w-full max-w-xl rounded-2xl border bg-muted object-cover"
              />
            )}
            {step.timer_minutes && (
              <div className="origin-left scale-125">
                <StepTimer key={step.id ?? index} minutes={step.timer_minutes} label={`шаг ${index + 1}`} />
              </div>
            )}
          </div>
        )}

        {/* Ингредиенты поверх шага */}
        {showIngredients && (
          <div className="absolute inset-0 overflow-y-auto bg-background/97 backdrop-blur-sm">
            <div className="mx-auto max-w-xl px-6 py-6">
              <h2 className="text-xl font-semibold">
                Ингредиенты · {servings} {plural(servings, "порция", "порции", "порций")}
              </h2>
              <ul className="mt-4 grid gap-1">
                {recipe.ingredients.map((ing, i) => {
                  const key = ing.id ?? i;
                  const on = checked.has(key);
                  const showGroup = ing.group && ing.group !== recipe.ingredients[i - 1]?.group;
                  return (
                    <li key={key}>
                      {showGroup && (
                        <h3 className="mt-5 mb-1 px-3 text-sm font-semibold text-muted-foreground">
                          {ing.group}
                        </h3>
                      )}
                      <button
                        className="flex w-full items-center gap-3 rounded-xl px-3 py-3 text-left text-lg hover:bg-muted"
                        onClick={() =>
                          setChecked((s) => {
                            const n = new Set(s);
                            if (n.has(key)) n.delete(key);
                            else n.add(key);
                            return n;
                          })
                        }
                      >
                        <span
                          className={cn(
                            "flex size-6 shrink-0 items-center justify-center rounded-md border-2",
                            on ? "border-success bg-success text-white" : "border-input",
                          )}
                        >
                          {on && <Check className="size-4" strokeWidth={3} />}
                        </span>
                        <span className={cn("flex-1", on && "text-muted-foreground line-through")}>{ing.product}</span>
                        <span className="font-bold whitespace-nowrap tabular-nums">
                          {ing.amount != null ? formatAmount(ing.amount * factor, ing.unit) : ""} {ing.unit}
                        </span>
                      </button>
                    </li>
                  );
                })}
              </ul>
              <Button className="mt-6 w-full" size="lg" onClick={() => setShowIngredients(false)}>
                К шагу {Math.min(index + 1, stepsCount)}
              </Button>
            </div>
          </div>
        )}
      </main>

      {/* Навигация */}
      {!finished && (
        <footer className="grid grid-cols-2 gap-3 border-t p-3 pb-[max(0.75rem,env(safe-area-inset-bottom))]">
          <Button variant="outline" size="lg" className="h-14 text-base" disabled={index === 0} onClick={() => go(-1)}>
            <ArrowLeft /> Назад
          </Button>
          <Button size="lg" className="h-14 text-base" onClick={() => go(1)}>
            {index === stepsCount - 1 ? (
              <>
                Готово <Check />
              </>
            ) : (
              <>
                Далее <ArrowRight />
              </>
            )}
          </Button>
        </footer>
      )}
    </div>
  );
}
