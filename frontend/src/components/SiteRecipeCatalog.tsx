import { useEffect, useState } from "react";
import { useSearchParams } from "react-router";
import { keepPreviousData, useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { Globe, Loader2, Search, X } from "lucide-react";
import { SiteRecipeCard } from "@/components/SiteRecipeCard";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { api } from "@/lib/api";
import { plural } from "@/lib/format";
import { useOnline } from "@/lib/offline";

const PAGE = 24;

export function SiteRecipeCatalog() {
  const [params, setParams] = useSearchParams();
  const q = params.get("site_q") ?? "";
  const sourceId = params.get("site_source") ? Number(params.get("site_source")) : undefined;
  const categoryId = params.get("site_category") ? Number(params.get("site_category")) : undefined;
  const [search, setSearch] = useState(q);
  const online = useOnline();
  useEffect(() => setSearch((current) => current.trim() === q ? current : q), [q]);
  useEffect(() => {
    const timer = setTimeout(() => {
      if (search.trim() === q) return;
      const next = new URLSearchParams(params);
      if (search.trim()) next.set("site_q", search.trim()); else next.delete("site_q");
      setParams(next, { replace: true });
    }, 300);
    return () => clearTimeout(timer);
  }, [search, q, params, setParams]);
  function setFilter(key: string, value: string) {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value); else next.delete(key);
    if (key === "site_source") next.delete("site_category");
    setParams(next, { replace: true });
  }
  function resetFilters() {
    const next = new URLSearchParams(params);
    for (const key of ["site_q", "site_source", "site_category"]) next.delete(key);
    setParams(next, { replace: true });
  }
  const sources = useQuery({ queryKey: ["site-recipes", "sources"], queryFn: api.siteRecipes.sources, enabled: online });
  const categories = useQuery({ queryKey: ["site-recipes", "categories", sourceId], queryFn: () => api.siteRecipes.categories(sourceId), enabled: online });
  const recipes = useInfiniteQuery({
    queryKey: ["site-recipes", "list", { q, sourceId, categoryId }],
    queryFn: ({ pageParam }) => api.siteRecipes.list({ source_id: sourceId, category_id: categoryId, q: q || undefined, limit: PAGE, offset: pageParam }),
    initialPageParam: 0,
    getNextPageParam: (last, pages) => {
      const loaded = pages.reduce((count, page) => count + page.items.length, 0);
      return loaded < last.total ? loaded : undefined;
    },
    placeholderData: keepPreviousData,
    enabled: online,
  });
  const items = recipes.data?.pages.flatMap((page) => page.items) ?? [];
  const total = recipes.data?.pages[0]?.total ?? 0;
  const filtered = Boolean(q || sourceId || categoryId);
  return (
    <div className="grid gap-6">
      <div><h1 className="title-display text-4xl sm:text-5xl">Рецепты сайтов</h1><p className="mt-2 max-w-2xl text-muted-foreground">Каталог подключённых источников. Откройте рецепт для просмотра и импортируйте его в свою коллекцию, когда понадобится.</p></div>
      {!online ? <p role="status" className="rounded-2xl bg-muted/60 p-5 text-sm text-muted-foreground">Для просмотра рецептов сайтов нужно подключение к интернету. Сохранённые рецепты доступны в коллекции.</p> : <>
        <div className="relative"><Search className="absolute top-1/2 left-4 size-4 -translate-y-1/2 text-muted-foreground" /><Input className="h-13 rounded-full bg-card pr-11 pl-11" aria-label="Поиск по рецептам сайтов" placeholder="Найти рецепт на подключённых сайтах" type="search" value={search} onChange={(event) => setSearch(event.target.value)} />{search && <button type="button" aria-label="Очистить поиск" className="absolute top-1/2 right-3 -translate-y-1/2 rounded-md p-1 text-muted-foreground" onClick={() => setSearch("")}><X className="size-4" /></button>}</div>
        <div className="grid gap-4 sm:grid-cols-2"><div className="grid gap-2"><label htmlFor="site-source" className="text-sm font-medium">Сайт</label><Select id="site-source" value={sourceId ?? ""} onChange={(event) => setFilter("site_source", event.target.value)} disabled={sources.isLoading || sources.isError}><option value="">Все сайты</option>{sources.data?.map((source) => <option key={source.id} value={source.id}>{source.name}</option>)}</Select></div><div className="grid gap-2"><label htmlFor="site-category" className="text-sm font-medium">Категория сайта</label><Select id="site-category" value={categoryId ?? ""} onChange={(event) => setFilter("site_category", event.target.value)} disabled={categories.isLoading || categories.isError}><option value="">Все категории</option>{categories.data?.map((category) => <option key={category.id} value={category.id}>{category.title}</option>)}</Select></div></div>
        {(sources.isError || categories.isError) && <p role="alert" className="text-sm text-destructive">{sources.error?.message ?? categories.error?.message}</p>}
        {recipes.isLoading ? <div className="flex justify-center py-20"><Loader2 className="size-6 animate-spin text-muted-foreground" /></div> : recipes.isError ? <div role="alert" className="rounded-2xl bg-destructive/10 p-5"><p className="text-sm text-destructive">{recipes.error.message}</p><Button variant="outline" className="mt-4" onClick={() => recipes.refetch()}>Повторить</Button></div> : items.length === 0 ? <div className="flex flex-col items-center rounded-3xl bg-muted/60 px-6 py-16 text-center"><Globe className="size-9 text-primary" strokeWidth={1.5} /><h2 className="mt-4 text-xl font-semibold">{filtered ? "Ничего не нашлось" : "Каталог пока пуст"}</h2><p className="mt-2 max-w-lg text-sm text-muted-foreground">{filtered ? "Попробуйте другой запрос или категорию." : "Здесь появятся рецепты источников, для которых администратор включил показ на сайте и обновил каталог."}</p>{filtered && <Button variant="outline" className="mt-5" onClick={resetFilters}>Сбросить фильтры</Button>}</div> : <><p className="text-sm text-muted-foreground">Найдено {total} {plural(total, "рецепт", "рецепта", "рецептов")}</p><div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3">{items.map((recipe) => <SiteRecipeCard key={recipe.id} recipe={recipe} />)}</div>{recipes.hasNextPage && <div className="flex justify-center"><Button variant="outline" disabled={recipes.isFetchingNextPage} onClick={() => recipes.fetchNextPage()}>{recipes.isFetchingNextPage && <Loader2 className="animate-spin" />} Показать ещё</Button></div>}</>}
      </>}
    </div>
  );
}
