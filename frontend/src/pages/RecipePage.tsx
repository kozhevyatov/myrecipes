import { useEffect, useMemo, useState, type ReactNode } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft,
  CalendarPlus,
  Home,
  Link2,
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
import { AddToPlanSheet } from "@/components/AddToPlanSheet";
import { Avatar } from "@/components/Avatar";
import { Lightbox } from "@/components/Lightbox";
import { ShareSheet } from "@/components/ShareSheet";
import { RecipeImage } from "@/components/RecipeCard";
import { CookLog } from "@/components/CookLog";
import { FavoriteButton } from "@/components/FavoriteButton";
import { NutritionCard } from "@/components/NutritionCard";
import { CostCard } from "@/components/CostCard";
import { StepTimer } from "@/components/StepTimer";
import { Button } from "@/components/ui/button";
import { Tag } from "@/components/ui/chip";
import { Switch } from "@/components/ui/switch";
import { ApiError, api, type Ingredient } from "@/lib/api";
import { DIFFICULTY, formatAmount, formatMinutes, plural } from "@/lib/format";
import { fromRecipe, sectionPath, useBackToSection } from "@/lib/nav";
import { useOfflineIds } from "@/lib/offline";
import { setLastList } from "@/lib/shoppingList";
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
  const back = useBackToSection();
  const query = useQuery({ queryKey: ["recipe", recipeId], queryFn: () => api.recipes.get(recipeId) });
  const recipe = query.data;

  const [servings, setServings] = useState(1);
  const [checked, setChecked] = useState<Set<number>>(new Set());
  const [doneSteps, setDoneSteps] = useState<Set<number>>(new Set());
  const [viewer, setViewer] = useState<{ photos: string[]; start: number } | null>(null);
  const [planOpen, setPlanOpen] = useState(false);
  const [shareOpen, setShareOpen] = useState(false);

  useEffect(() => {
    if (recipe) {
      setServings(recipe.servings);
      document.title = recipe.title;
    }
  }, [recipe]);

  // То, что есть дома, сразу отмечено — в покупки не попадёт
  const recipeKey = recipe?.id;
  useEffect(() => {
    if (recipe) setChecked(new Set(recipe.ingredients.filter((i) => i.in_pantry && i.id).map((i) => i.id!)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [recipeKey]);

  const remove = useMutation({
    mutationFn: () => api.recipes.remove(recipeId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["recipes"] });
      queryClient.invalidateQueries({ queryKey: ["categories"] });
      queryClient.invalidateQueries({ queryKey: ["tags"] });
      toast.success("Рецепт удалён");
      navigate(sectionPath(), { replace: true });
    },
    onError: (e) => toast.error(e.message),
  });

  const groups = useMemo(() => groupIngredients(recipe?.ingredients ?? []), [recipe]);
  const offlineIds = useOfflineIds();

  // Отмеченные галочкой ингредиенты считаем «уже есть дома» и в покупки не добавляем
  const shoppingLists = useQuery({ queryKey: ["shopping-lists"], queryFn: api.shopping.lists });
  // По умолчанию — отдельный список этого рецепта (0); можно выбрать и обычный список
  const [targetList, setTargetList] = useState<number>(0);
  const lists = shoppingLists.data ?? [];
  const ownRecipeList = lists.find((l) => l.recipe_id === recipeId && l.is_owner);
  const otherLists = lists.filter((l) => l.recipe_id === null);
  const target = targetList ? otherLists.find((l) => l.id === targetList) : undefined;
  const toBuy = useMutation({
    mutationFn: async () => {
      const ids = (recipe?.ingredients ?? []).map((i) => i.id!).filter((id) => !checked.has(id));
      if (target) {
        const r = await api.shopping.fromRecipe(target.id, recipeId, servings, ids);
        return { listId: target.id, name: target.name, items: r.items, created: false, merged: r.merged };
      }
      const r = await api.shopping.recipeList(recipeId, servings, ids);
      return { listId: r.shopping_list.id, name: r.shopping_list.name, items: r.items, created: r.created, merged: 0 };
    },
    onSuccess: (r) => {
      setLastList(r.listId);
      queryClient.setQueryData(["shopping", r.listId], r.items);
      queryClient.invalidateQueries({ queryKey: ["shopping-lists"] });
      toast.success(
        target ? `Добавлено в «${r.name}»` : r.created ? `Создан список «${r.name}»` : `Список «${r.name}» обновлён`,
        {
          description: target
            ? r.merged
              ? `сложено с уже имеющимися: ${r.merged}`
              : undefined
            : `${r.items.length} ${plural(r.items.length, "продукт", "продукта", "продуктов")}`,
          action: { label: "Открыть", onClick: () => navigate("/shopping") },
        },
      );
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
          <Link to={sectionPath()}>К рецептам</Link>
        </Button>
      </div>
    );
  }

  const factor = servings / recipe.servings;
  const gallery = [recipe.image_url, ...(recipe.photos ?? []).map((p) => p.url)].filter(Boolean) as string[];
  const galleryThumbs = [recipe.thumb_url ?? recipe.image_url, ...(recipe.photos ?? []).map((p) => p.thumb_url ?? p.url)].filter(
    Boolean,
  ) as string[];
  const stepPhotos = recipe.steps.filter((s) => s.image_url).map((s) => s.image_url!);
  const toggle = (set: Set<number>, key: number) => {
    const next = new Set(set);
    if (next.has(key)) next.delete(key);
    else next.add(key);
    return next;
  };

  return (
    <article className="mx-auto grid max-w-5xl gap-8">
      <div className="flex items-center justify-between gap-2 print:hidden">
        <Button variant="ghost" size="sm" onClick={back}>
          <ArrowLeft /> Назад
        </Button>
        <div className="flex items-center gap-2">
          <FavoriteButton key={`${recipe.id}-${recipe.is_favorite}`} recipeId={recipe.id} initial={recipe.is_favorite} className="size-8" />
          <Button variant="ghost" size="icon" className="size-8" onClick={() => window.print()} aria-label="Печать" title="Печать">
            <Printer />
          </Button>
          {recipe.can_edit && (
            <Button
              variant="ghost"
              size="icon"
              className={cn("size-8", recipe.share_url && "text-primary")}
              onClick={() => setShareOpen(true)}
              aria-label="Поделиться ссылкой"
              title={recipe.share_url ? "Ссылка включена" : "Поделиться ссылкой"}
            >
              <Link2 />
            </Button>
          )}
        {recipe.can_edit && (
          <>
            <Button asChild variant="outline" size="sm" aria-label="Изменить">
              <Link to={`/recipes/${recipe.id}/edit`} state={fromRecipe}>
                <Pencil /> <span className="hidden sm:inline">Изменить</span>
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
        <div className="grid gap-2">
          <button
            type="button"
            className="aspect-[4/3] overflow-hidden rounded-3xl border bg-muted print:rounded-xl"
            onClick={() => gallery.length && setViewer({ photos: gallery, start: 0 })}
            disabled={!recipe.image_url}
            aria-label="Открыть фото"
          >
            <RecipeImage src={recipe.image_url} alt={recipe.title} />
          </button>
          {galleryThumbs.length > 1 && (
            <div className="flex gap-2 overflow-x-auto pb-1 [scrollbar-width:none] print:hidden">
              {galleryThumbs.map((src, i) => (
                <button
                  key={src + i}
                  type="button"
                  onClick={() => setViewer({ photos: gallery, start: i })}
                  className="size-16 shrink-0 overflow-hidden rounded-xl border bg-muted sm:size-20"
                  aria-label={`Фото ${i + 1}`}
                >
                  <img src={src} alt="" loading="lazy" className="h-full w-full object-cover" />
                </button>
              ))}
            </div>
          )}
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
                <Link to={`/recipes/${recipe.id}/cook?servings=${servings}`} state={fromRecipe}>
                  <ChefHat /> Начать готовить
                </Link>
              </Button>
            )}
            <Button variant="outline" size="lg" className="print:hidden" onClick={() => setPlanOpen(true)}>
              <CalendarPlus /> В меню
            </Button>
            {recipe.is_favorite && offlineIds.has(recipe.id) && (
              <span className="flex items-center gap-1.5 text-sm text-muted-foreground print:hidden" title="Откроется без интернета">
                <Check className="size-4 text-success" /> на устройстве
              </span>
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
                                {ing.in_pantry && (
                                  <span className="ml-1.5 inline-flex translate-y-[-1px] items-center gap-0.5 rounded-full bg-success/12 px-1.5 py-px align-middle text-[11px] font-medium text-success no-underline print:hidden">
                                    <Home className="size-3" /> дома
                                  </span>
                                )}
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
                {(!target && ownRecipeList ? "Обновить список покупок" : "В список покупок") +
                  (checked.size > 0 ? `: ${recipe.ingredients.length - checked.size} из ${recipe.ingredients.length}` : "")}
              </Button>
            )}
            {recipe.ingredients.length > 0 && (
              <label className="mt-2 flex items-center justify-center gap-2 text-xs text-muted-foreground print:hidden">
                в
                <select
                  className="max-w-[14rem] rounded-md border bg-card px-2 py-1 text-xs text-foreground"
                  value={targetList}
                  onChange={(e) => setTargetList(Number(e.target.value))}
                >
                  <option value={0}>{ownRecipeList ? `список «${ownRecipeList.name}»` : "отдельный список рецепта"}</option>
                  {otherLists.map((l) => (
                    <option key={l.id} value={l.id}>
                      «{l.name}»
                    </option>
                  ))}
                </select>
              </label>
            )}
            {checked.size > 0 && checked.size < recipe.ingredients.length && (
              <p className="mt-2 text-center text-xs text-muted-foreground print:hidden">
                Отмеченные считаются «уже есть»
                {recipe.ingredients.some((i) => i.in_pantry) && " — то, что есть дома, отмечено само"}
              </p>
            )}
          </div>
          {recipe.nutrition && <NutritionCard nutrition={recipe.nutrition} servings={recipe.servings} />}
          {recipe.cost && <CostCard cost={recipe.cost} recipeId={recipe.id} servings={recipe.servings} />}
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
                      {step.image_url && (
                        <button
                          type="button"
                          className="w-full max-w-sm overflow-hidden rounded-xl border bg-muted print:max-w-[12rem]"
                          onClick={() => setViewer({ photos: stepPhotos, start: stepPhotos.indexOf(step.image_url!) })}
                          aria-label={`Фото к шагу ${i + 1}`}
                        >
                          <img src={step.thumb_url ?? step.image_url} alt="" loading="lazy" className="aspect-[4/3] w-full object-cover" />
                        </button>
                      )}
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

      {viewer && <Lightbox photos={viewer.photos} start={viewer.start} onClose={() => setViewer(null)} />}
      {planOpen && <AddToPlanSheet recipe={recipe} onClose={() => setPlanOpen(false)} />}
      {shareOpen && <ShareSheet recipe={recipe} onClose={() => setShareOpen(false)} />}
    </article>
  );
}
