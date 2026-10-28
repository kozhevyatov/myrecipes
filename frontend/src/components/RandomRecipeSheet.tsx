import { useEffect, useState } from "react";
import { Link } from "react-router";
import { useQuery } from "@tanstack/react-query";
import { CalendarPlus, Clock, Dices, Loader2 } from "lucide-react";
import { AddToPlanSheet } from "@/components/AddToPlanSheet";
import { RecipeImage } from "@/components/RecipeCard";
import { Button } from "@/components/ui/button";
import { Chip } from "@/components/ui/chip";
import { Sheet } from "@/components/ui/sheet";
import { Switch } from "@/components/ui/switch";
import { ApiError, api, type RandomQuery, type RecipeListItem } from "@/lib/api";
import { formatMinutes } from "@/lib/format";

const TIMES = [
  { label: "Любое время", value: undefined },
  { label: "до 30 мин", value: 30 },
  { label: "до 1 часа", value: 60 },
];

/** «Что приготовить?» — случайный рецепт под настроение. */
export function RandomRecipeSheet({ onClose }: { onClose: () => void }) {
  const categories = useQuery({ queryKey: ["categories"], queryFn: api.catalog.categories });
  const [category, setCategory] = useState<number | undefined>();
  const [favorites, setFavorites] = useState(false);
  const [maxMinutes, setMaxMinutes] = useState<number | undefined>();
  const [fresh, setFresh] = useState(true);
  const [recipe, setRecipe] = useState<RecipeListItem | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [shown, setShown] = useState<number[]>([]);
  const [planOpen, setPlanOpen] = useState(false);

  async function roll(reset = false) {
    setLoading(true);
    setError(null);
    const exclude = reset ? [] : shown;
    const params: RandomQuery = {
      category_id: category,
      favorites,
      max_minutes: maxMinutes,
      not_cooked_days: fresh ? 14 : undefined,
      exclude: exclude.slice(-50).join(",") || undefined,
    };
    try {
      const r = await api.recipes.random(params);
      setRecipe(r);
      setShown([...exclude, r.id]);
    } catch (e) {
      setRecipe(null);
      setError(e instanceof ApiError && e.status === 404 ? "Под эти условия ничего не нашлось — ослабьте фильтры." : (e as Error).message);
    } finally {
      setLoading(false);
    }
  }

  // Новый подбор при смене фильтров
  useEffect(() => {
    roll(true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [category, favorites, maxMinutes, fresh]);

  if (planOpen && recipe) return <AddToPlanSheet recipe={recipe} onClose={() => setPlanOpen(false)} />;

  return (
    <Sheet
      title="Что приготовить?"
      onClose={onClose}
      className="sm:max-w-lg"
      footer={
        <>
          <Button variant="outline" onClick={() => roll()} disabled={loading}>
            {loading ? <Loader2 className="animate-spin" /> : <Dices />} Другой вариант
          </Button>
          {recipe && (
            <Button asChild>
              <Link to={`/recipes/${recipe.id}`} onClick={onClose}>
                Открыть
              </Link>
            </Button>
          )}
        </>
      }
    >
      <div className="-mx-6 flex gap-2 overflow-x-auto px-6 pb-1 [scrollbar-width:none]">
        <Chip active={category === undefined} onClick={() => setCategory(undefined)} className="h-8 px-3">
          Всё
        </Chip>
        {categories.data
          ?.filter((c) => c.recipe_count > 0)
          .map((c) => (
            <Chip key={c.id} active={category === c.id} onClick={() => setCategory(c.id)} className="h-8 px-3">
              {c.name}
            </Chip>
          ))}
      </div>
      <div className="mt-2 flex flex-wrap gap-2">
        {TIMES.map((t) => (
          <Chip key={t.label} active={maxMinutes === t.value} onClick={() => setMaxMinutes(t.value)} className="h-8 px-3">
            {t.label}
          </Chip>
        ))}
      </div>
      <div className="mt-3 grid gap-2 text-sm">
        <label className="flex items-center justify-between gap-3">
          Только избранное <Switch checked={favorites} onCheckedChange={setFavorites} />
        </label>
        <label className="flex items-center justify-between gap-3">
          Не готовил последние 2 недели <Switch checked={fresh} onCheckedChange={setFresh} />
        </label>
      </div>

      <div className="mt-4">
        {error ? (
          <p className="rounded-2xl bg-muted/60 px-4 py-10 text-center text-sm text-muted-foreground">{error}</p>
        ) : recipe ? (
          <div className={loading ? "opacity-60 transition-opacity" : "transition-opacity"}>
            <Link to={`/recipes/${recipe.id}`} onClick={onClose} className="block overflow-hidden rounded-2xl border bg-muted">
              <div className="aspect-[16/10]">
                <RecipeImage src={recipe.thumb_url ?? recipe.image_url} alt={recipe.title} />
              </div>
            </Link>
            <div className="mt-3 flex items-start justify-between gap-3">
              <div className="min-w-0">
                <h3 className="text-lg leading-snug font-semibold">{recipe.title}</h3>
                <p className="mt-0.5 flex items-center gap-1.5 text-sm text-muted-foreground">
                  {recipe.category?.name}
                  {recipe.total_minutes != null && (
                    <>
                      {recipe.category && " · "}
                      <Clock className="size-3.5" /> {formatMinutes(recipe.total_minutes)}
                    </>
                  )}
                </p>
              </div>
              <Button variant="ghost" size="sm" className="shrink-0" onClick={() => setPlanOpen(true)}>
                <CalendarPlus /> В меню
              </Button>
            </div>
          </div>
        ) : (
          <div className="flex justify-center py-16">
            <Loader2 className="size-6 animate-spin text-muted-foreground" />
          </div>
        )}
      </div>
    </Sheet>
  );
}
