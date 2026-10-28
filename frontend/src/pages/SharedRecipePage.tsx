import { useEffect, useMemo, useState, type ReactNode } from "react";
import { Link, useParams } from "react-router";
import { useQuery } from "@tanstack/react-query";
import { Check, Clock, ExternalLink, Flame, Gauge, Loader2, Minus, Plus, User } from "lucide-react";
import { Brand } from "@/components/Logo";
import { Lightbox } from "@/components/Lightbox";
import { NutritionCard } from "@/components/NutritionCard";
import { RecipeImage } from "@/components/RecipeCard";
import { StepTimer } from "@/components/StepTimer";
import { Button } from "@/components/ui/button";
import { Tag } from "@/components/ui/chip";
import { api, type Ingredient } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { DIFFICULTY, formatAmount, formatMinutes, plural } from "@/lib/format";
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

function group(list: Ingredient[]) {
  const groups: { name: string; items: Ingredient[] }[] = [];
  for (const ing of list) {
    const last = groups[groups.length - 1];
    if (last && last.name === ing.group) last.items.push(ing);
    else groups.push({ name: ing.group, items: [ing] });
  }
  return groups;
}

/** Рецепт по публичной ссылке: только чтение, без входа. */
export default function SharedRecipePage() {
  const { token = "" } = useParams();
  const { user } = useAuth();
  const query = useQuery({ queryKey: ["shared", token], queryFn: () => api.recipes.shared(token), retry: false });
  const recipe = query.data;
  const [servings, setServings] = useState(1);
  const [checked, setChecked] = useState<Set<number>>(new Set());
  const [viewer, setViewer] = useState<{ photos: string[]; start: number } | null>(null);
  const groups = useMemo(() => group(recipe?.ingredients ?? []), [recipe]);

  useEffect(() => {
    if (recipe) {
      setServings(recipe.servings);
      document.title = `${recipe.title} — ${recipe.site_name}`;
    }
  }, [recipe]);

  const header = (
    <header className="border-b print:hidden">
      <div className="mx-auto flex h-16 max-w-5xl items-center justify-between gap-4 px-4 sm:px-6">
        <Brand name={recipe?.site_name ?? "Мои рецепты"} />
        {user ? (
          <Button asChild variant="outline" size="sm">
            <Link to="/">К моим рецептам</Link>
          </Button>
        ) : (
          <Button asChild variant="ghost" size="sm">
            <Link to="/login">Войти</Link>
          </Button>
        )}
      </div>
    </header>
  );

  if (query.isLoading)
    return (
      <div className="min-h-svh">
        {header}
        <div className="flex justify-center py-24">
          <Loader2 className="size-6 animate-spin text-muted-foreground" />
        </div>
      </div>
    );

  if (!recipe)
    return (
      <div className="min-h-svh">
        {header}
        <div className="mx-auto max-w-md px-6 py-24 text-center">
          <h1 className="title-display text-3xl">Рецепт недоступен</h1>
          <p className="mt-3 text-muted-foreground">{(query.error as Error)?.message ?? "Ссылка не работает"}</p>
        </div>
      </div>
    );

  const factor = servings / recipe.servings;
  const gallery = [recipe.image_url, ...recipe.photos.map((p) => p.url)].filter(Boolean) as string[];
  const thumbs = [recipe.image_url, ...recipe.photos.map((p) => p.thumb_url ?? p.url)].filter(Boolean) as string[];
  const stepPhotos = recipe.steps.filter((s) => s.image_url).map((s) => s.image_url!);

  return (
    <div className="min-h-svh">
      {header}
      <article className="mx-auto grid max-w-5xl gap-8 px-4 py-8 sm:px-6 sm:py-10">
        <header className="grid gap-8 md:grid-cols-[1.15fr_1fr] md:items-center print:grid-cols-[14rem_1fr] print:gap-6">
          <div className="grid gap-2">
            <button
              type="button"
              className="aspect-[4/3] overflow-hidden rounded-3xl border bg-muted"
              onClick={() => gallery.length && setViewer({ photos: gallery, start: 0 })}
              disabled={!recipe.image_url}
              aria-label="Открыть фото"
            >
              <RecipeImage src={recipe.image_url} alt={recipe.title} />
            </button>
            {thumbs.length > 1 && (
              <div className="flex gap-2 overflow-x-auto pb-1 [scrollbar-width:none] print:hidden">
                {thumbs.map((src, i) => (
                  <button
                    key={src + i}
                    type="button"
                    onClick={() => setViewer({ photos: gallery, start: i })}
                    className="size-16 shrink-0 overflow-hidden rounded-xl border bg-muted sm:size-20"
                  >
                    <img src={src} alt="" loading="lazy" className="h-full w-full object-cover" />
                  </button>
                ))}
              </div>
            )}
          </div>
          <div className="grid gap-5">
            {recipe.category && (
              <span className="justify-self-start rounded-full bg-accent px-3 py-1 text-xs font-medium text-accent-foreground">
                {recipe.category}
              </span>
            )}
            <h1 className="title-display text-[2rem] sm:text-[2.75rem]">{recipe.title}</h1>
            {recipe.description && <p className="leading-relaxed whitespace-pre-line text-muted-foreground">{recipe.description}</p>}
            <div className="flex flex-wrap gap-x-6 gap-y-3">
              {recipe.prep_minutes != null && (
                <Meta icon={<Clock className="size-4" />} label="Подготовка" value={formatMinutes(recipe.prep_minutes)!} />
              )}
              {recipe.cook_minutes != null && (
                <Meta icon={<Flame className="size-4" />} label="Готовка" value={formatMinutes(recipe.cook_minutes)!} />
              )}
              {recipe.difficulty && <Meta icon={<Gauge className="size-4" />} label="Сложность" value={DIFFICULTY[recipe.difficulty]} />}
              <Meta icon={<User className="size-4" />} label="Автор" value={recipe.author} />
            </div>
            {recipe.source_url && (
              <a
                href={recipe.source_url}
                target="_blank"
                rel="noopener noreferrer nofollow"
                className="flex items-center gap-1.5 text-sm font-semibold text-muted-foreground hover:text-foreground"
              >
                <ExternalLink className="size-4" /> Источник
              </a>
            )}
            {recipe.tags.length > 0 && (
              <div className="flex flex-wrap gap-1.5">
                {recipe.tags.map((t) => (
                  <Tag key={t}>{t}</Tag>
                ))}
              </div>
            )}
          </div>
        </header>

        <div className="grid gap-8 lg:grid-cols-[minmax(0,22rem)_1fr] lg:items-start print:grid-cols-1">
          <section className="grid gap-4 lg:sticky lg:top-6">
            <div className="rounded-3xl border bg-card p-5 sm:p-6 print:border-0 print:p-0">
              <div className="flex items-center justify-between gap-3">
                <h2 className="text-xl font-semibold">Ингредиенты</h2>
                <div className="flex items-center gap-1 rounded-full bg-muted p-1 print:hidden">
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
              <div className="mt-4 grid gap-5">
                {groups.map((g, gi) => (
                  <div key={gi}>
                    {g.name && <h3 className="mb-1.5 px-2 text-sm font-semibold text-muted-foreground">{g.name}</h3>}
                    <ul className="grid gap-0.5">
                      {g.items.map((ing, i) => {
                        const key = ing.id ?? gi * 1000 + i;
                        const on = checked.has(key);
                        return (
                          <li key={key}>
                            <button
                              onClick={() =>
                                setChecked((s) => {
                                  const n = new Set(s);
                                  if (n.has(key)) n.delete(key);
                                  else n.add(key);
                                  return n;
                                })
                              }
                              className="flex w-full items-start gap-3 rounded-lg px-2 py-2 text-left hover:bg-muted/60"
                            >
                              <span
                                className={cn(
                                  "mt-0.5 flex size-5 shrink-0 items-center justify-center rounded-md border-2",
                                  on ? "border-success bg-success text-white" : "border-input",
                                )}
                              >
                                {on && <Check className="size-3.5" strokeWidth={3} />}
                              </span>
                              <span className={cn("flex-1 text-[15px]", on && "text-muted-foreground line-through")}>
                                {ing.product}
                                {ing.note && <span className="text-muted-foreground">, {ing.note}</span>}
                              </span>
                              <span className="shrink-0 text-[15px] font-semibold whitespace-nowrap tabular-nums">
                                {ing.amount != null ? formatAmount(ing.amount * factor, ing.unit) : ""} {ing.unit}
                              </span>
                            </button>
                          </li>
                        );
                      })}
                    </ul>
                  </div>
                ))}
              </div>
            </div>
            {recipe.nutrition && <NutritionCard nutrition={recipe.nutrition} servings={recipe.servings} readOnly />}
          </section>

          <section>
            <h2 className="text-xl font-semibold">Приготовление</h2>
            <ol className="mt-4 grid gap-3">
              {recipe.steps.map((step, i) => (
                <li key={step.id ?? i} className="flex gap-4 rounded-2xl border bg-card p-4 sm:p-5 print:border-0 print:p-0">
                  <span className="flex size-9 shrink-0 items-center justify-center rounded-full bg-accent text-sm font-semibold text-accent-foreground tabular-nums">
                    {i + 1}
                  </span>
                  <div className="grid flex-1 gap-3 pt-1">
                    <p className="max-w-prose text-base leading-relaxed whitespace-pre-line">{step.text}</p>
                    {step.image_url && (
                      <button
                        type="button"
                        className="w-full max-w-sm overflow-hidden rounded-xl border bg-muted"
                        onClick={() => setViewer({ photos: stepPhotos, start: stepPhotos.indexOf(step.image_url!) })}
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
              ))}
            </ol>
          </section>
        </div>

        <footer className="border-t pt-6 text-center text-sm text-muted-foreground print:hidden">
          Рецепт из книги «{recipe.site_name}»
        </footer>
      </article>
      {viewer && <Lightbox photos={viewer.photos} start={viewer.start} onClose={() => setViewer(null)} />}
    </div>
  );
}
