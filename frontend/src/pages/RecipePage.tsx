import { useEffect, useMemo, useState, type ReactNode } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft,
  Printer,
  ShoppingBasket,
  Check,
  ChefHat,
  Clock,
  ExternalLink,
  Flame,
  Gauge,
  Loader2,
  Lock,
  Minus,
  Pencil,
  Plus,
  Sun,
  Trash2,
} from "lucide-react";
import { toast } from "sonner";
import { Avatar } from "@/components/Avatar";
import { RecipeImage } from "@/components/RecipeCard";
import { CookLog } from "@/components/CookLog";
import { FavoriteButton } from "@/components/FavoriteButton";
import { NutritionCard } from "@/components/NutritionCard";
import { StepTimer } from "@/components/StepTimer";
import { Button } from "@/components/ui/button";
import { Tag } from "@/components/ui/chip";
import { Switch } from "@/components/ui/switch";
import { ApiError, api, type Ingredient } from "@/lib/api";
import { DIFFICULTY, formatAmount, formatMinutes, plural } from "@/lib/format";
import { useWakeLock } from "@/lib/useWakeLock";
import { cn } from "@/lib/utils";

function Meta({ icon, label, value }: { icon: ReactNode; label: string; value: string }) {
  return (
    <div className="flex items-center gap-2.5">
      <span className="flex size-9 items-center justify-center rounded-full bg-accent text-accent-foreground">{icon}</span>
      <span className="leading-tight">
        <span className="block text-xs text-muted-foreground">{label}</span>
        <span className="block text-sm font-semibold">{value}</span>
      </span>
    </div>
  );
}

function KeepScreenOn() {
  const wake = useWakeLock();
  if (!wake.supported) return null;
  return (
    <label className="flex cursor-pointer items-center justify-between gap-3 rounded-xl border bg-card px-4 py-3 print:hidden">
      <span className="flex items-center gap-2.5 text-sm font-semibold">
        <Sun className={cn("size-4", wake.active ? "text-primary" : "text-muted-foreground")} />
        Не гасить экран
      </span>
      <Switch checked={wake.enabled} onCheckedChange={wake.setEnabled} />
    </label>
  );
}

function groupIngredients(list: Ingredient[]) {
  const groups: { name: string; items: Ingredient[] }[] = [];
  for (const ing of list) {
    const last = groups[groups.length - 1];
    if (last && last.name === ing.group) last.items.push(ing);
    else groups.push({ name: ing.group, items: [ing] });
  }
  return groups;
}

export default function RecipePage() {
  const { id } = useParams();
  const recipeId = Number(id);
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const query = useQuery({ queryKey: ["recipe", recipeId], queryFn: () => api.recipes.get(recipeId) });
  const recipe = query.data;

  const [servings, setServings] = useState(1);
  const [checked, setChecked] = useState<Set<number>>(new Set());
  const [doneSteps, setDoneSteps] = useState<Set<number>>(new Set());

  useEffect(() => {
    if (recipe) {
      setServings(recipe.servings);
      document.title = recipe.title;
    }
  }, [recipe]);

  const remove = useMutation({
    mutationFn: () => api.recipes.remove(recipeId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["recipes"] });
      queryClient.invalidateQueries({ queryKey: ["categories"] });
      queryClient.invalidateQueries({ queryKey: ["tags"] });
      toast.success("Рецепт удалён");
      navigate("/", { replace: true });
    },
    onError: (e) => toast.error(e.message),
  });

  const groups = useMemo(() => groupIngredients(recipe?.ingredients ?? []), [recipe]);

  // Отмеченные галочкой ингредиенты считаем «уже есть дома» и в покупки не добавляем
  const toBuy = useMutation({
    mutationFn: () => {
      const ids = (recipe?.ingredients ?? []).map((i) => i.id!).filter((id) => !checked.has(id));
      return api.shopping.fromRecipe(recipeId, servings, ids);
    },
    onSuccess: (r) => {
      queryClient.setQueryData(["shopping"], r.items);
      const parts = [];
      if (r.added) parts.push(`добавлено ${r.added}`);
      if (r.merged) parts.push(`сложено с уже имеющимися ${r.merged}`);
      toast.success("В списке покупок", {
        description: parts.join(", ") || undefined,
        action: { label: "Открыть", onClick: () => navigate("/shopping") },
      });
    },
    onError: (e) => toast.error(e.message),
  });

  if (query.isLoading)
    return (
      <div className="flex justify-center py-20">
        <Loader2 className="size-6 animate-spin text-muted-foreground" />
      </div>
    );

  if (!recipe) {
    const notFound = query.error instanceof ApiError && query.error.status === 404;
    return (
      <div className="py-20 text-center">
        <h1 className="text-2xl font-bold">{notFound ? "Рецепт не найден" : "Не удалось загрузить рецепт"}</h1>
        <Button asChild variant="outline" className="mt-6">
          <Link to="/">К рецептам</Link>
        </Button>
      </div>
    );
  }

  const factor = servings / recipe.servings;
  const toggle = (set: Set<number>, key: number) => {
    const next = new Set(set);
    if (next.has(key)) next.delete(key);
    else next.add(key);
    return next;
  };

  return (
    <article className="mx-auto grid max-w-5xl gap-8">
      <div className="flex items-center justify-between gap-2 print:hidden">
        <Button variant="ghost" size="sm" onClick={() => (history.length > 1 ? navigate(-1) : navigate("/"))}>
          <ArrowLeft /> Назад
        </Button>
        <div className="flex items-center gap-2">
          <FavoriteButton key={`${recipe.id}-${recipe.is_favorite}`} recipeId={recipe.id} initial={recipe.is_favorite} className="size-8" />
          <Button variant="ghost" size="icon" className="size-8" onClick={() => window.print()} aria-label="Печать" title="Печать">
            <Printer />
          </Button>
        {recipe.can_edit && (
          <>
            <Button asChild variant="outline" size="sm">
              <Link to={`/recipes/${recipe.id}/edit`}>
                <Pencil /> Изменить
              </Link>
            </Button>
            <Button
              variant="ghost"
              size="sm"
              className="text-destructive hover:text-destructive"
              disabled={remove.isPending}
              onClick={() => {
                if (confirm(`Удалить рецепт «${recipe.title}»?`)) remove.mutate();
              }}
            >
              <Trash2 />
            </Button>
          </>
        )}
        </div>
      </div>

      {/* Шапка */}
      <header className="grid gap-8 md:grid-cols-[1.15fr_1fr] md:items-center print:grid-cols-[14rem_1fr] print:gap-6">
        <div className="aspect-[4/3] overflow-hidden rounded-3xl border bg-muted print:rounded-xl">
          <RecipeImage src={recipe.image_url} alt={recipe.title} />
        </div>
        <div className="grid gap-5">
          <div className="flex flex-wrap items-center gap-2">
            {recipe.category && (
              <Link
                to={`/?category=${recipe.category.id}`}
                className="rounded-full bg-accent px-3 py-1 text-xs font-medium text-accent-foreground hover:bg-accent/70"
              >
                {recipe.category.name}
              </Link>
            )}
            {!recipe.is_public && (
              <span className="flex items-center gap-1 text-xs font-semibold text-muted-foreground">
                <Lock className="size-3" /> только для вас
              </span>
            )}
          </div>
          <h1 className="title-display text-[2rem] sm:text-[2.75rem]">{recipe.title}</h1>
          {recipe.description && (
            <p className="leading-relaxed whitespace-pre-line text-muted-foreground">{recipe.description}</p>
          )}
          <div className="flex flex-wrap gap-x-6 gap-y-3">
            {recipe.prep_minutes != null && (
              <Meta icon={<Clock className="size-4" />} label="Подготовка" value={formatMinutes(recipe.prep_minutes)!} />
            )}
            {recipe.cook_minutes != null && (
              <Meta icon={<Flame className="size-4" />} label="Готовка" value={formatMinutes(recipe.cook_minutes)!} />
            )}
            {recipe.difficulty && (
              <Meta icon={<Gauge className="size-4" />} label="Сложность" value={DIFFICULTY[recipe.difficulty]} />
            )}
            <div className="flex items-center gap-2.5">
              <Avatar src={recipe.author.avatar_url} name={recipe.author.name} />
              <span className="leading-tight">
                <span className="block text-xs text-muted-foreground">Автор</span>
                <span className="block text-sm font-semibold">{recipe.author.name}</span>
              </span>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-3">
            {recipe.steps.length > 0 && (
              <Button asChild size="lg" className="print:hidden">
                <Link to={`/recipes/${recipe.id}/cook?servings=${servings}`}>
                  <ChefHat /> Начать готовить
                </Link>
              </Button>
            )}
            {recipe.source_url && (
              <a
                href={recipe.source_url}
                target="_blank"
                rel="noopener noreferrer"
                className="flex items-center gap-1.5 text-sm font-semibold text-muted-foreground hover:text-foreground"
              >
                <ExternalLink className="size-4" />
                {(() => {
                  try {
                    return new URL(recipe.source_url).hostname.replace(/^www\./, "");
                  } catch {
                    return "Источник";
                  }
                })()}
              </a>
            )}
          </div>
          {recipe.tags.length > 0 && (
            <div className="flex flex-wrap gap-1.5">
              {recipe.tags.map((t) => (
                <Link key={t} to={`/?tag=${encodeURIComponent(t)}`}>
                  <Tag className="hover:bg-accent/70">{t}</Tag>
                </Link>
              ))}
            </div>
          )}
        </div>
      </header>

      <div className="grid gap-8 lg:grid-cols-[minmax(0,22rem)_1fr] lg:items-start print:grid-cols-1 print:gap-5">
        {/* Ингредиенты */}
        <section className="grid gap-4 lg:sticky lg:top-24">
          <KeepScreenOn />
          <div className="rounded-3xl border bg-card p-5 sm:p-6 print:border-0 print:p-0">
            <div className="flex items-center justify-between gap-3">
              <h2 className="text-xl font-semibold">Ингредиенты</h2>
              <div className="flex items-center gap-1 rounded-full bg-muted p-1 print:bg-transparent print:p-0">
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
            {servings !== recipe.servings && (
              <button
                className="mt-2 text-xs font-semibold text-primary hover:underline"
                onClick={() => setServings(recipe.servings)}
              >
                Вернуть {recipe.servings} {plural(recipe.servings, "порцию", "порции", "порций")}, как в рецепте
              </button>
            )}

            {recipe.ingredients.length === 0 ? (
              <p className="mt-4 text-sm text-muted-foreground">Ингредиенты не указаны.</p>
            ) : (
              <div className="mt-4 grid gap-5">
                {groups.map((g, gi) => (
                  <div key={gi}>
                    {g.name && (
                      <h3 className="mb-1.5 px-2 text-sm font-semibold text-muted-foreground">{g.name}</h3>
                    )}
                    <ul className="grid gap-0.5">
                      {g.items.map((ing, i) => {
                        const key = ing.id ?? gi * 1000 + i;
                        const isChecked = checked.has(key);
                        const amount = ing.amount != null ? formatAmount(ing.amount * factor, ing.unit) : "";
                        return (
                          <li key={key}>
                            <button
                              onClick={() => setChecked((s) => toggle(s, key))}
                              className="flex w-full items-start gap-3 rounded-lg px-2 py-2 text-left hover:bg-muted/60 print:py-0.5"
                            >
                              <span
                                className={cn(
                                  "mt-0.5 flex size-5 shrink-0 items-center justify-center rounded-md border-2 transition-colors",
                                  isChecked ? "border-success bg-success text-white" : "border-input",
                                )}
                              >
                                {isChecked && <Check className="size-3.5" strokeWidth={3} />}
                              </span>
                              <span className={cn("flex-1 text-[15px]", isChecked && "text-muted-foreground line-through")}>
                                {ing.product}
                                {ing.note && <span className="text-muted-foreground">, {ing.note}</span>}
                              </span>
                              <span
                                className={cn(
                                  "shrink-0 text-[15px] font-semibold whitespace-nowrap tabular-nums",
                                  isChecked && "text-muted-foreground",
                                )}
                              >
                                {amount} {ing.unit}
                              </span>
                            </button>
                          </li>
                        );
                      })}
                    </ul>
                  </div>
                ))}
              </div>
            )}
            {recipe.ingredients.length > 0 && (
              <Button
                variant="secondary"
                className="mt-5 w-full print:hidden"
                disabled={toBuy.isPending || checked.size >= recipe.ingredients.length}
                onClick={() => toBuy.mutate()}
              >
                {toBuy.isPending ? <Loader2 className="animate-spin" /> : <ShoppingBasket />}
                {checked.size > 0
                  ? `В список покупок: ${recipe.ingredients.length - checked.size} из ${recipe.ingredients.length}`
                  : "В список покупок"}
              </Button>
            )}
            {checked.size > 0 && checked.size < recipe.ingredients.length && (
              <p className="mt-2 text-center text-xs text-muted-foreground">Отмеченные считаются «уже есть»</p>
            )}
          </div>
          {recipe.nutrition && <NutritionCard nutrition={recipe.nutrition} servings={recipe.servings} />}
        </section>

        {/* Шаги */}
        <section>
          <h2 className="text-xl font-semibold">Приготовление</h2>
          {recipe.steps.length === 0 ? (
            <p className="mt-4 text-sm text-muted-foreground">Шаги не описаны.</p>
          ) : (
            <ol className="mt-4 grid gap-3">
              {recipe.steps.map((step, i) => {
                const key = step.id ?? i;
                const done = doneSteps.has(key);
                return (
                  <li
                    key={key}
                    className={cn(
                      "flex gap-4 rounded-2xl border bg-card p-4 transition-opacity sm:p-5 print:border-0 print:p-0 print:py-1.5",
                      done && "opacity-55",
                    )}
                  >
                    <button
                      onClick={() => setDoneSteps((s) => toggle(s, key))}
                      className={cn(
                        "flex size-9 shrink-0 items-center justify-center rounded-full text-sm font-semibold tabular-nums transition-colors",
                        done ? "bg-success text-white" : "bg-accent text-accent-foreground hover:bg-primary hover:text-primary-foreground",
                      )}
                      aria-label={done ? "Отметить как невыполненный" : "Отметить как выполненный"}
                    >
                      {done ? <Check className="size-4" strokeWidth={3} /> : i + 1}
                    </button>
                    <div className="grid flex-1 gap-3 pt-1">
                      <p className="max-w-prose text-base leading-relaxed whitespace-pre-line">{step.text}</p>
                      {step.timer_minutes && (
                        <div>
                          <StepTimer minutes={step.timer_minutes} label={`шаг ${i + 1}`} />
                        </div>
                      )}
                    </div>
                  </li>
                );
              })}
            </ol>
          )}
        </section>
      </div>

      <CookLog recipe={recipe} />
    </article>
  );
}
