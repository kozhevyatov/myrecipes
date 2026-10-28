import { useState } from "react";
import { Link, useNavigate } from "react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChefHat, Home, Loader2, Plus, ShoppingBasket, Sparkles, UtensilsCrossed, X } from "lucide-react";
import { toast } from "sonner";
import { RecipeCard } from "@/components/RecipeCard";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { api, type PantryItem, type RecipeMatch } from "@/lib/api";
import { formatMinutes, plural } from "@/lib/format";
import { getLastList, setLastList } from "@/lib/shoppingList";

// Что обычно есть на кухне — добавить в один тап
const STAPLES = [
  "Соль",
  "Сахар",
  "Перец черный молотый",
  "Масло растительное",
  "Масло сливочное",
  "Мука пшеничная",
  "Яйца",
  "Молоко",
  "Лук репчатый",
  "Чеснок",
  "Морковь",
  "Картофель",
  "Рис",
  "Макароны",
  "Сметана",
  "Сыр твердый",
];

function MissingRow({ match, onBuy, buying }: { match: RecipeMatch; onBuy: () => void; buying: boolean }) {
  const r = match.recipe;
  return (
    <li className="flex items-center gap-3 rounded-2xl border bg-card p-3">
      <Link to={`/recipes/${r.id}`} className="flex min-w-0 flex-1 items-center gap-3">
        <div className="size-14 shrink-0 overflow-hidden rounded-xl bg-accent">
          {r.thumb_url ? (
            <img src={r.thumb_url} alt="" loading="lazy" className="h-full w-full object-cover" />
          ) : (
            <UtensilsCrossed className="m-4 size-6 text-primary/40" />
          )}
        </div>
        <span className="min-w-0">
          <span className="block truncate font-semibold">{r.title}</span>
          <span className="block text-xs text-muted-foreground">
            есть {match.have} из {match.need}
            {r.total_minutes ? ` · ${formatMinutes(r.total_minutes)}` : ""}
          </span>
          <span className="mt-0.5 block text-sm text-muted-foreground">
            не хватает: <span className="font-medium text-foreground">{match.missing.join(", ").toLowerCase()}</span>
          </span>
        </span>
      </Link>
      <Button variant="ghost" size="icon" className="shrink-0" onClick={onBuy} disabled={buying} title="Недостающее — в покупки" aria-label="Недостающее — в список покупок">
        {buying ? <Loader2 className="animate-spin" /> : <ShoppingBasket />}
      </Button>
    </li>
  );
}

export default function PantryPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [text, setText] = useState("");
  const [showMore, setShowMore] = useState(false);
  const pantry = useQuery({ queryKey: ["pantry"], queryFn: api.pantry.list });
  const products = useQuery({ queryKey: ["products"], queryFn: api.catalog.products, staleTime: 60_000 });
  const matches = useQuery({ queryKey: ["pantry-match"], queryFn: api.recipes.match, enabled: Boolean(pantry.data?.length) });
  const lists = useQuery({ queryKey: ["shopping-lists"], queryFn: api.shopping.lists });

  const updated = (items: PantryItem[]) => {
    queryClient.setQueryData(["pantry"], items);
    queryClient.invalidateQueries({ queryKey: ["pantry-match"] });
    queryClient.invalidateQueries({ queryKey: ["recipe"] }); // отметки «дома» на страницах рецептов
  };
  const add = useMutation({
    mutationFn: (name: string) => api.pantry.add(name),
    onSuccess: (items) => {
      updated(items);
      setText("");
    },
    onError: (e) => toast.error(e.message),
  });
  const remove = useMutation({ mutationFn: api.pantry.remove, onSuccess: updated, onError: (e) => toast.error(e.message) });
  const clear = useMutation({ mutationFn: api.pantry.clear, onSuccess: updated, onError: (e) => toast.error(e.message) });

  const [buyingId, setBuyingId] = useState<number | null>(null);
  async function buyMissing(m: RecipeMatch) {
    const target = lists.data?.find((l) => l.id === getLastList()) ?? lists.data?.[0];
    if (!target) return;
    setBuyingId(m.recipe.id);
    try {
      const r = await api.shopping.fromProducts(target.id, m.missing, m.recipe.title);
      setLastList(target.id);
      queryClient.setQueryData(["shopping", target.id], r.items);
      queryClient.invalidateQueries({ queryKey: ["shopping-lists"] });
      toast.success(`Недостающее — в «${target.name}»`, {
        description: m.missing.join(", ").toLowerCase(),
        action: { label: "Открыть", onClick: () => navigate("/shopping") },
      });
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setBuyingId(null);
    }
  }

  const items = pantry.data ?? [];
  const have = new Set(items.map((i) => i.name.toLowerCase()));
  const staples = STAPLES.filter((s) => !have.has(s.toLowerCase()));
  const all = matches.data?.items ?? [];
  const ready = all.filter((m) => m.missing.length === 0);
  const almost = all.filter((m) => m.missing.length > 0 && m.missing.length <= 2);
  const more = all.filter((m) => m.missing.length > 2);

  return (
    <div className="grid min-w-0 grid-cols-1 gap-8">
      <div>
        <h1 className="title-display text-4xl sm:text-5xl">Что есть дома</h1>
        <p className="mt-2 max-w-2xl text-muted-foreground">
          Отметьте продукты, которые сейчас есть, — покажем, что из них приготовить. Их же не будем добавлять в список
          покупок из меню и рецептов.
        </p>
      </div>

      <section className="grid gap-4 rounded-3xl border bg-card p-5 sm:p-7">
        <form
          className="flex gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            if (text.trim()) add.mutate(text.trim());
          }}
        >
          <Input
            list="pantry-products"
            placeholder="Курица, гречка, помидоры…"
            value={text}
            onChange={(e) => setText(e.target.value)}
            enterKeyHint="done"
          />
          <Button type="submit" disabled={!text.trim() || add.isPending} className="h-11 shrink-0">
            {add.isPending ? <Loader2 className="animate-spin" /> : <Plus />} <span className="hidden sm:inline">Добавить</span>
          </Button>
          <datalist id="pantry-products">
            {products.data?.filter((p) => !have.has(p.toLowerCase())).map((p) => <option key={p} value={p} />)}
          </datalist>
        </form>

        {items.length > 0 ? (
          <div className="flex flex-wrap gap-1.5">
            {items.map((i) => (
              <span key={i.product_id} className="flex items-center gap-1 rounded-full bg-success/12 py-1.5 pr-1.5 pl-3 text-sm font-medium text-success">
                {i.name}
                <button
                  className="flex size-5 items-center justify-center rounded-full hover:bg-success/20"
                  onClick={() => remove.mutate(i.product_id)}
                  aria-label={`Убрать ${i.name}`}
                >
                  <X className="size-3.5" />
                </button>
              </span>
            ))}
            <button
              className="px-2 text-sm font-medium text-muted-foreground hover:text-destructive"
              onClick={() => confirm("Убрать все продукты?") && clear.mutate()}
            >
              Очистить
            </button>
          </div>
        ) : (
          !pantry.isLoading && (
            <p className="flex items-center gap-2 text-sm text-muted-foreground">
              <Home className="size-4" /> Пока пусто — начните с того, что есть всегда.
            </p>
          )
        )}

        {staples.length > 0 && (
          <div>
            <p className="mb-2 text-xs font-semibold tracking-wide text-muted-foreground uppercase">Частое</p>
            <div className="flex flex-wrap gap-1.5">
              {staples.map((s) => (
                <button
                  key={s}
                  className="flex items-center gap-1 rounded-full border border-dashed border-input px-3 py-1 text-sm text-muted-foreground transition-colors hover:border-primary hover:text-foreground"
                  onClick={() => add.mutate(s)}
                  disabled={add.isPending}
                >
                  <Plus className="size-3.5" /> {s}
                </button>
              ))}
            </div>
          </div>
        )}
      </section>

      {items.length > 0 &&
        (matches.isLoading ? (
          <div className="flex justify-center py-10">
            <Loader2 className="size-6 animate-spin text-muted-foreground" />
          </div>
        ) : all.length === 0 ? (
          <div className="flex flex-col items-center rounded-3xl bg-muted/60 px-6 py-14 text-center">
            <div className="rounded-2xl bg-card p-4">
              <ChefHat className="size-8 text-primary" strokeWidth={1.5} />
            </div>
            <h2 className="mt-5 text-xl font-bold">Пока ничего не подходит</h2>
            <p className="mt-2 max-w-sm text-sm text-muted-foreground">Добавьте ещё продуктов — рецепты появятся, когда большей части ингредиентов будет хватать.</p>
          </div>
        ) : (
          <>
            {ready.length > 0 && (
              <section className="grid gap-4">
                <h2 className="flex items-center gap-2 text-xl font-semibold">
                  <Sparkles className="size-5 text-primary" /> Можно готовить
                  <span className="text-base font-normal text-muted-foreground">{ready.length}</span>
                </h2>
                <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
                  {ready.map((m) => (
                    <RecipeCard key={m.recipe.id} recipe={m.recipe} />
                  ))}
                </div>
              </section>
            )}
            {almost.length > 0 && (
              <section className="grid grid-cols-1 gap-3">
                <h2 className="text-xl font-semibold">
                  Почти всё есть <span className="text-base font-normal text-muted-foreground">не хватает 1–2 продуктов</span>
                </h2>
                <ul className="grid grid-cols-1 gap-2 md:grid-cols-2">
                  {almost.map((m) => (
                    <MissingRow key={m.recipe.id} match={m} onBuy={() => buyMissing(m)} buying={buyingId === m.recipe.id} />
                  ))}
                </ul>
              </section>
            )}
            {more.length > 0 && (
              <section className="grid grid-cols-1 gap-3">
                {showMore ? (
                  <>
                    <h2 className="text-xl font-semibold">Нужно докупить</h2>
                    <ul className="grid grid-cols-1 gap-2 md:grid-cols-2">
                      {more.map((m) => (
                        <MissingRow key={m.recipe.id} match={m} onBuy={() => buyMissing(m)} buying={buyingId === m.recipe.id} />
                      ))}
                    </ul>
                  </>
                ) : (
                  <Button variant="outline" className="h-auto min-h-10 justify-self-center py-2 text-center whitespace-normal" onClick={() => setShowMore(true)}>
                    Ещё {more.length} {plural(more.length, "рецепт", "рецепта", "рецептов")}, где не хватает 3–5 продуктов
                  </Button>
                )}
              </section>
            )}
          </>
        ))}
    </div>
  );
}
