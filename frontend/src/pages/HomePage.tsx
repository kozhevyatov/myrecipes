import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router";
import { keepPreviousData, useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { ChefHat, Loader2, Plus, Search, X } from "lucide-react";
import { RecipeCard } from "@/components/RecipeCard";
import { Button } from "@/components/ui/button";
import { Chip } from "@/components/ui/chip";
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { plural } from "@/lib/format";
import { useOnline } from "@/lib/offline";

const PAGE = 24;

export default function HomePage() {
  const { user } = useAuth();
  const [params, setParams] = useSearchParams();
  const q = params.get("q") ?? "";
  const categoryId = params.get("category") ? Number(params.get("category")) : undefined;
  const tag = params.get("tag") ?? undefined;
  const mine = params.get("mine") === "1";
  const favorites = params.get("fav") === "1";

  // Поле поиска обновляет URL с небольшой задержкой
  const [search, setSearch] = useState(q);
  // Синхронизация из URL (назад/вперёд, сброс фильтров) — не трогаем пробел, который пользователь сейчас набирает
  useEffect(() => {
    setSearch((s) => (s.trim() === q ? s : q));
  }, [q]);
  useEffect(() => {
    const t = setTimeout(() => {
      if (search.trim() === q) return;
      setParam("q", search.trim() || null);
    }, 300);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search]);

  function setParam(key: string, value: string | null) {
    const next = new URLSearchParams(params);
    if (value === null) next.delete(key);
    else next.set(key, value);
    setParams(next, { replace: true });
  }

  const categories = useQuery({ queryKey: ["categories"], queryFn: api.catalog.categories });
  const tags = useQuery({ queryKey: ["tags"], queryFn: api.catalog.tags });

  const recipes = useInfiniteQuery({
    queryKey: ["recipes", { q, categoryId, tag, mine, favorites }],
    queryFn: ({ pageParam }) =>
      api.recipes.list({ q: q || undefined, category_id: categoryId, tag, mine, favorites, limit: PAGE, offset: pageParam }),
    initialPageParam: 0,
    getNextPageParam: (last, pages) => {
      const loaded = pages.reduce((n, p) => n + p.items.length, 0);
      return loaded < last.total ? loaded : undefined;
    },
    placeholderData: keepPreviousData,
  });

  const items = recipes.data?.pages.flatMap((p) => p.items) ?? [];
  const total = recipes.data?.pages[0]?.total ?? 0;
  const filtered = Boolean(q || categoryId || tag || mine || favorites);
  const name = user?.display_name || user?.username;
  const online = useOnline();

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
        <Button asChild size="lg">
          <Link to="/recipes/new">
            <Plus /> Новый рецепт
          </Link>
        </Button>
      </div>

      <div className="relative">
        <Search className="absolute top-1/2 left-4 size-4 -translate-y-1/2 text-muted-foreground" />
        <Input
          className="h-13 rounded-full border-transparent bg-card pr-11 pl-11 shadow-[0_1px_2px_rgb(0_0_0/0.04),0_0_0_1px_var(--border)] focus-visible:shadow-none"
          placeholder="Название, тег или ингредиент — например, «курица рис»"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          type="search"
          enterKeyHint="search"
        />
        {search && (
          <button
            className="absolute top-1/2 right-3 -translate-y-1/2 rounded-md p-1 text-muted-foreground hover:text-foreground"
            onClick={() => setSearch("")}
            aria-label="Очистить"
          >
            <X className="size-4" />
          </button>
        )}
      </div>

      {/* Фильтры: горизонтальная прокрутка на телефоне */}
      <div className="-mx-4 flex gap-2 overflow-x-auto px-4 pb-1 [scrollbar-width:none] sm:mx-0 sm:flex-wrap sm:px-0">
        <Chip active={!categoryId && !mine && !favorites} onClick={() => setParams(new URLSearchParams(q ? { q } : {}), { replace: true })}>
          Все
        </Chip>
        <Chip active={favorites} onClick={() => setParam("fav", favorites ? null : "1")}>
          Избранное
        </Chip>
        <Chip active={mine} onClick={() => setParam("mine", mine ? null : "1")}>
          Мои
        </Chip>
        {categories.data?.map((c) => (
          <Chip
            key={c.id}
            active={categoryId === c.id}
            onClick={() => setParam("category", categoryId === c.id ? null : String(c.id))}
          >
            {c.name}
            {c.recipe_count > 0 && <span className="opacity-60">{c.recipe_count}</span>}
          </Chip>
        ))}
      </div>

      {tags.data && tags.data.length > 0 && (
        <div className="-mt-2 flex flex-wrap gap-1.5">
          {tags.data.slice(0, 20).map((t) => (
            <button
              key={t.name}
              onClick={() => setParam("tag", tag === t.name ? null : t.name)}
              className={
                tag === t.name
                  ? "rounded-full bg-highlight px-3 py-1 text-xs font-medium text-highlight-foreground"
                  : "rounded-full bg-accent px-3 py-1 text-xs font-medium text-accent-foreground hover:bg-accent/70"
              }
            >
              {t.name}
            </button>
          ))}
        </div>
      )}

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
              <Button variant="outline" className="mt-6" onClick={() => setParams(new URLSearchParams(), { replace: true })}>
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
