import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router";
import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { ChefHat, Dices, Home, Loader2, Plus } from "lucide-react";
import { RandomRecipeSheet } from "@/components/RandomRecipeSheet";
import { RecipeCard } from "@/components/RecipeCard";
import { SiteRecipeCatalog } from "@/components/SiteRecipeCatalog";
import { Button } from "@/components/ui/button";
import { Chip } from "@/components/ui/chip";
import { RecipeFilters } from "@/components/RecipeFilters";
import { RecipeSearch } from "@/components/RecipeSearch";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { plural } from "@/lib/format";
import { useOnline } from "@/lib/offline";

const PAGE = 24;

export default function HomePage() {
  const [params, setParams] = useSearchParams();
  const siteCatalog = params.get("view") === "sites";
  function chooseCatalog(external: boolean) {
    const next = new URLSearchParams(params);
    if (external) next.set("view", "sites"); else next.delete("view");
    setParams(next, { replace: true });
  }
  return <div className="grid gap-6"><div className="flex flex-wrap gap-2" aria-label="Каталог рецептов"><Chip active={!siteCatalog} aria-pressed={!siteCatalog} onClick={() => chooseCatalog(false)}>Коллекция</Chip><Chip active={siteCatalog} aria-pressed={siteCatalog} onClick={() => chooseCatalog(true)}>Рецепты сайтов</Chip></div>{siteCatalog ? <SiteRecipeCatalog /> : <LocalRecipesPage />}</div>;
}

function LocalRecipesPage() {
  const { user } = useAuth();
  const [params, setParams] = useSearchParams();
  const q = params.get("q") ?? "";
  const categoryId = params.get("category") ? Number(params.get("category")) : undefined;
  const selectedTags = [...new Set(params.getAll("tag").map((name) => name.trim().toLowerCase()).filter(Boolean))];
  const mine = params.get("mine") === "1";
  const favorites = params.get("fav") === "1";
  const sourceId = params.get("source") ? Number(params.get("source")) : undefined;

  // Update the URL after typing settles.
  const [search, setSearch] = useState(q);
  // Preserve trailing spaces while typing, but follow navigation and filter resets.
  useEffect(() => {
    setSearch((s) => (s.trim() === q ? s : q));
  }, [q]);
  useEffect(() => {
    if (search.trim() === q) return;
    const t = setTimeout(() => {
      setParams((current) => {
        const next = new URLSearchParams(current);
        if (search.trim()) next.set("q", search.trim());
        else next.delete("q");
        return next;
      }, { replace: true });
    }, 300);
    return () => clearTimeout(t);
  }, [search, q, setParams]);

  function setParam(key: string, value: string | null) {
    const next = new URLSearchParams(params);
    if (value === null) next.delete(key);
    else next.set(key, value);
    setParams(next, { replace: true });
  }

  function clearParams(keys: string[]) {
    const next = new URLSearchParams(params);
    for (const key of keys) next.delete(key);
    setParams(next, { replace: true });
  }

  function resetFilters() {
    setSearch("");
    clearParams(["q", "category", "tag", "source", "mine", "fav"]);
  }

  function addTag(name: string) {
    const normalized = name.trim().toLowerCase();
    if (!normalized || selectedTags.includes(normalized) || selectedTags.length >= 20) return;
    setSearch("");
    setParams((current) => {
      const next = new URLSearchParams(current);
      const names = [...new Set([...current.getAll("tag").map((value) => value.trim().toLowerCase()), normalized])];
      next.delete("q");
      next.delete("tag");
      for (const value of names.filter(Boolean)) next.append("tag", value);
      return next;
    }, { replace: true });
  }

  function removeTag(name: string) {
    setParams((current) => {
      const next = new URLSearchParams(current);
      next.delete("tag");
      for (const value of current.getAll("tag")) {
        if (value.trim().toLowerCase() !== name) next.append("tag", value);
      }
      return next;
    }, { replace: true });
  }

  const categories = useQuery({ queryKey: ["categories"], queryFn: api.catalog.categories });
  const tags = useQuery({ queryKey: ["tags"], queryFn: api.catalog.tags });
  const sources = useQuery({ queryKey: ["recipe-sources"], queryFn: api.imports.catalogSources });

  const recipes = useInfiniteQuery({
    queryKey: ["recipes", { q, categoryId, tags: selectedTags, mine, favorites, sourceId }],
    queryFn: ({ pageParam }) =>
      api.recipes.list({ q: q || undefined, category_id: categoryId, tags: selectedTags, mine, favorites, source_id: sourceId, limit: PAGE, offset: pageParam }),
    initialPageParam: 0,
    getNextPageParam: (last, pages) => {
      const loaded = pages.reduce((n, p) => n + p.items.length, 0);
      return loaded < last.total ? loaded : undefined;
    },
  });

  const items = recipes.data?.pages.flatMap((p) => p.items) ?? [];
  const total = recipes.data?.pages[0]?.total ?? 0;
  const filtered = Boolean(q || categoryId || selectedTags.length || mine || favorites || sourceId);
  const name = user?.display_name || user?.username;
  const online = useOnline();
  const [randomOpen, setRandomOpen] = useState(false);

  return (
    <div className="grid gap-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="title-display text-4xl sm:text-5xl">Рецепты</h1>
          {!online && <p className="mt-2 text-muted-foreground">Без связи — показываем избранное, сохранённое на устройстве</p>}
          {online && !filtered && total > 0 && (
            <p className="mt-2 text-muted-foreground">
              {name}, в книге {total} {plural(total, "рецепт", "рецепта", "рецептов")}
            </p>
          )}
        </div>
        <div className="flex flex-wrap gap-2">
          <Button asChild size="lg">
            <Link to="/recipes/new">
              <Plus /> Новый рецепт
            </Link>
          </Button>
          {online && (
            <>
              <Button variant="outline" size="lg" onClick={() => setRandomOpen(true)}>
                <Dices /> Что приготовить?
              </Button>
              <Button asChild variant="outline" size="lg">
                <Link to="/pantry">
                  <Home /> Что есть дома
                </Link>
              </Button>
            </>
          )}
        </div>
      </div>
      {randomOpen && <RandomRecipeSheet onClose={() => setRandomOpen(false)} />}

      <RecipeSearch
        value={search}
        onChange={setSearch}
        onSelectTag={addTag}
        filters={{ category_id: categoryId, tags: selectedTags, source_id: sourceId, mine, favorites }}
        online={online}
      />

      <RecipeFilters
        categoryId={categoryId}
        selectedTags={selectedTags}
        onAddTag={addTag}
        onRemoveTag={removeTag}
        sourceId={sourceId}
        mine={mine}
        favorites={favorites}
        searchActive={Boolean(q)}
        categories={{ items: categories.data ?? [], loading: categories.isLoading, error: categories.error?.message, retry: () => { categories.refetch(); } }}
        tags={{ items: tags.data ?? [], loading: tags.isLoading, error: tags.error?.message, retry: () => { tags.refetch(); } }}
        sources={{ items: sources.data ?? [], loading: sources.isLoading, error: sources.error?.message, retry: () => { sources.refetch(); } }}
        onChange={setParam}
        onAll={() => clearParams(["category", "tag", "source", "mine", "fav"])}
        onReset={resetFilters}
      />

      {recipes.isLoading ? (
        <div className="flex justify-center py-20">
          <Loader2 className="size-6 animate-spin text-muted-foreground" />
        </div>
      ) : items.length === 0 ? (
        <div className="flex flex-col items-center rounded-3xl bg-muted/60 px-6 py-20 text-center">
          <div className="rounded-2xl bg-card p-4">
            <ChefHat className="size-8 text-primary" strokeWidth={1.5} />
          </div>
          {filtered ? (
            <>
              <h2 className="mt-5 text-xl font-bold">Ничего не нашлось</h2>
              <p className="mt-2 max-w-sm text-sm text-muted-foreground">Попробуйте другой запрос или сбросьте фильтры.</p>
              <Button variant="outline" className="mt-6" onClick={resetFilters}>
                Сбросить фильтры
              </Button>
            </>
          ) : (
            <>
              <h2 className="mt-5 text-xl font-bold">Здесь пока пусто</h2>
              <p className="mt-2 max-w-sm text-sm text-muted-foreground">
                Добавьте первый рецепт: с фото, ингредиентами в граммах и пошаговым приготовлением.
              </p>
              <Button asChild className="mt-6">
                <Link to="/recipes/new">
                  <Plus /> Добавить рецепт
                </Link>
              </Button>
            </>
          )}
        </div>
      ) : (
        <>
          {filtered && (
            <p className="-mb-2 text-sm text-muted-foreground">
              Найдено {total} {plural(total, "рецепт", "рецепта", "рецептов")}
            </p>
          )}
          <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
            {items.map((r) => (
              <RecipeCard key={r.id} recipe={r} />
            ))}
          </div>
          {recipes.hasNextPage && (
            <div className="flex justify-center">
              <Button variant="outline" onClick={() => recipes.fetchNextPage()} disabled={recipes.isFetchingNextPage}>
                {recipes.isFetchingNextPage && <Loader2 className="animate-spin" />} Показать ещё
              </Button>
            </div>
          )}
        </>
      )}
    </div>
  );
}
