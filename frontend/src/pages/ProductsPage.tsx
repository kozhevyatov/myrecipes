import { Fragment, useEffect, useMemo, useState, type ChangeEvent } from "react";
import { useSearchParams } from "react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronDown, Copy, Loader2, Merge, Search, Trash2, X } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Chip } from "@/components/ui/chip";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { api, type DuplicateGroup, type PriceUnit, type Product, type ProductPatch } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { formatMoney } from "@/lib/format";
import { cn } from "@/lib/utils";

type NumKey = "kcal" | "protein" | "fat" | "carbs" | "piece_grams" | "density";
const COLUMNS: { key: NumKey; label: string; hint: string }[] = [
  { key: "kcal", label: "Ккал", hint: "на 100 г" },
  { key: "protein", label: "Белки", hint: "г на 100 г" },
  { key: "fat", label: "Жиры", hint: "г на 100 г" },
  { key: "carbs", label: "Углев.", hint: "г на 100 г" },
  { key: "piece_grams", label: "1 шт, г", hint: "вес одной штуки — для «шт», «зубчик», «пучок»" },
  { key: "density", label: "г/мл", hint: "плотность — для мл, ложек и стаканов; вода = 1" },
];

const toStr = (v: number | null) => (v === null || v === undefined ? "" : String(v).replace(".", ","));
const toNum = (s: string) => {
  const t = s.trim().replace(",", ".");
  if (!t) return null;
  const n = Number(t);
  return Number.isFinite(n) ? n : undefined; // undefined — некорректный ввод
};

function NumCell({ product, k, onSave }: { product: Product; k: NumKey; onSave: (patch: ProductPatch) => void }) {
  const [value, setValue] = useState(toStr(product[k]));
  useEffect(() => setValue(toStr(product[k])), [product, k]);
  const commit = () => {
    const n = toNum(value);
    if (n === undefined) return setValue(toStr(product[k]));
    if (n !== product[k]) onSave({ [k]: n } as ProductPatch);
  };
  return (
    <input
      inputMode="decimal"
      className="h-9 w-full rounded-lg border border-transparent bg-transparent px-2 text-right text-sm tabular-nums transition-colors outline-none hover:border-input focus:border-primary focus:bg-card focus:ring-4 focus:ring-ring/30"
      value={value}
      placeholder="—"
      onChange={(e) => setValue(e.target.value.replace(/[^\d.,]/g, ""))}
      onBlur={commit}
      onKeyDown={(e) => e.key === "Enter" && (e.target as HTMLInputElement).blur()}
      aria-label={COLUMNS.find((c) => c.key === k)?.label}
    />
  );
}

const PRICE_UNITS: PriceUnit[] = ["г", "кг", "мл", "л", "шт"];

function invalidateCosts(queryClient: ReturnType<typeof useQueryClient>) {
  queryClient.invalidateQueries({ queryKey: ["recipe"] });
  queryClient.invalidateQueries({ queryKey: ["recipe-cost-history"] });
}

function shortDate(iso: string) {
  return new Date(iso).toLocaleDateString("ru-RU", { day: "numeric", month: "short", year: "2-digit" });
}

function PriceCell({ product, onClick }: { product: Product; onClick: () => void }) {
  const pr = product.price;
  return (
    <button
      className="h-9 w-full rounded-lg px-2 text-right text-sm leading-tight transition-colors hover:bg-muted"
      onClick={onClick}
      title="Цены продукта"
    >
      {pr ? (
        <>
          <span className="tabular-nums">
            {formatMoney(pr.price)}
            <span className="text-muted-foreground">
              {" "}
              / {toStr(pr.package_amount)} {pr.package_unit}
            </span>
          </span>
          {pr.unit_price !== null && pr.unit_label && (
            <span className="block text-[11px] text-muted-foreground tabular-nums">
              {formatMoney(pr.unit_price)}/{pr.unit_label}
            </span>
          )}
        </>
      ) : (
        <span className="text-muted-foreground">—</span>
      )}
    </button>
  );
}

/** Ввод цены «как на ценнике» и история цен продукта. */
function PriceRow({ product, onDone }: { product: Product; onDone: () => void }) {
  const queryClient = useQueryClient();
  const last = product.price;
  const [price, setPrice] = useState("");
  const [amount, setAmount] = useState(last ? toStr(last.package_amount) : "");
  const [unit, setUnit] = useState<PriceUnit>(last?.package_unit ?? (product.piece_grams ? "шт" : "г"));
  const history = useQuery({
    queryKey: ["product-prices", product.id],
    queryFn: () => api.catalog.productPrices(product.id),
  });
  const onProduct = (p: Product) => {
    queryClient.setQueryData<Product[]>(["product-catalog"], (list) => list?.map((x) => (x.id === p.id ? p : x)));
    queryClient.invalidateQueries({ queryKey: ["product-prices", product.id] });
    invalidateCosts(queryClient);
  };
  const add = useMutation({
    mutationFn: () =>
      api.catalog.addPrice(product.id, { price: toNum(price) as number, package_amount: toNum(amount) as number, package_unit: unit }),
    onSuccess: (p) => {
      onProduct(p);
      setPrice("");
      toast.success(`Цена «${p.name}» сохранена`);
    },
    onError: (e) => toast.error(e.message),
  });
  const remove = useMutation({
    mutationFn: (id: number) => api.catalog.deletePrice(id),
    onSuccess: onProduct,
    onError: (e) => toast.error(e.message),
  });
  const valid = !!toNum(price) && !!toNum(amount);
  const decimal = (set: (v: string) => void) => (e: ChangeEvent<HTMLInputElement>) =>
    set(e.target.value.replace(/[^\d.,]/g, ""));

  return (
    <div className="grid gap-3 rounded-xl bg-muted/60 p-3 text-sm">
      <form
        className="flex flex-wrap items-center gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          if (valid) add.mutate();
        }}
      >
        <span>Цена на ценнике:</span>
        <Input className="h-9 w-24 text-right" inputMode="decimal" placeholder="220" value={price} onChange={decimal(setPrice)} autoFocus />
        <span>₽ за</span>
        <Input className="h-9 w-20 text-right" inputMode="decimal" placeholder="180" value={amount} onChange={decimal(setAmount)} />
        <div className="w-20">
          <Select className="h-9" value={unit} onChange={(e) => setUnit(e.target.value as PriceUnit)}>
            {PRICE_UNITS.map((u) => (
              <option key={u} value={u}>
                {u}
              </option>
            ))}
          </Select>
        </div>
        <Button size="sm" type="submit" disabled={!valid || add.isPending}>
          Сохранить
        </Button>
        <Button size="sm" variant="ghost" type="button" onClick={onDone}>
          Закрыть
        </Button>
      </form>
      {unit === "шт" && !product.piece_grams && (
        <p className="text-xs text-muted-foreground">
          Цена за штуки подойдёт рецептам, где продукт тоже в штуках. Чтобы считалось и по граммам — укажите вес 1 шт.
        </p>
      )}
      {history.data && history.data.length > 0 && (
        <ul className="grid gap-1 text-xs text-muted-foreground">
          {history.data.slice(0, 6).map((h) => (
            <li key={h.id} className="flex items-center gap-2">
              <span className="w-20 shrink-0">{shortDate(h.created_at)}</span>
              <span className="text-foreground tabular-nums">
                {formatMoney(h.price)} / {toStr(h.package_amount)} {h.package_unit}
              </span>
              {h.unit_price !== null && h.unit_label && (
                <span className="tabular-nums">
                  ({formatMoney(h.unit_price)}/{h.unit_label})
                </span>
              )}
              {h.author && <span className="truncate">· {h.author}</span>}
              {h.can_delete && (
                <button
                  className="ml-auto p-1 hover:text-destructive"
                  title="Удалить цену"
                  aria-label="Удалить цену"
                  onClick={() => confirm("Удалить эту цену?") && remove.mutate(h.id)}
                >
                  <X className="size-3.5" />
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** Похожие продукты: объединение дублей в один клик. */
function DuplicatesPanel() {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const dupes = useQuery({ queryKey: ["product-duplicates"], queryFn: api.catalog.duplicates });
  const groups = dupes.data ?? [];
  if (groups.length === 0) return null;
  return (
    <div className="rounded-3xl border bg-card">
      <button className="flex w-full items-center gap-3 px-5 py-4 text-left" onClick={() => setOpen(!open)}>
        <Copy className="size-4 text-primary" />
        <span className="font-semibold">Похоже на дубли</span>
        <span className="text-sm text-muted-foreground">{groups.length}</span>
        <ChevronDown className={cn("ml-auto size-4 transition-transform", open && "rotate-180")} />
      </button>
      {open && (
        <div className="grid gap-3 border-t px-5 py-4">
          <p className="text-xs leading-relaxed text-muted-foreground">
            Отметьте, что объединить, и выберите главный продукт. Ингредиенты, цены и КБЖУ перейдут к нему, а старые
            названия запомнятся — при импорте рецептов они сами попадут в главный продукт.
          </p>
          {groups.map((g) => (
            <DuplicateGroupRow key={g.products.map((p) => p.id).join("-")} group={g} onDone={() => {
              queryClient.invalidateQueries({ queryKey: ["product-duplicates"] });
              queryClient.invalidateQueries({ queryKey: ["product-catalog"] });
              queryClient.invalidateQueries({ queryKey: ["products"] });
              invalidateCosts(queryClient);
            }} />
          ))}
        </div>
      )}
    </div>
  );
}

function DuplicateGroupRow({
  group,
  onDone,
}: {
  group: DuplicateGroup;
  onDone: () => void;
}) {
  const [main, setMain] = useState(group.products[0].id);
  const [picked, setPicked] = useState<Set<number>>(
    () => new Set(group.products.filter((p) => p.exact).map((p) => p.id)),
  );
  const merge = useMutation({
    mutationFn: async () => {
      const ids = group.products.map((p) => p.id).filter((id) => id !== main && picked.has(id));
      for (const id of ids) await api.catalog.mergeProduct(id, main);
      return ids.length;
    },
    onSuccess: (n) => {
      toast.success(`Объединено: ${n}`);
      onDone();
    },
    onError: (e) => {
      toast.error(e.message);
      onDone();
    },
  });
  const count = group.products.filter((p) => p.id !== main && picked.has(p.id)).length;
  const mainName = group.products.find((p) => p.id === main)?.name;
  return (
    <div className="rounded-2xl bg-muted/60 p-3">
      <ul className="grid gap-1.5 text-sm">
        {group.products.map((p) => (
          <li key={p.id} className="flex flex-wrap items-center gap-2">
            <input
              type="checkbox"
              className="size-4 accent-primary"
              checked={p.id === main || picked.has(p.id)}
              disabled={p.id === main}
              onChange={(e) => {
                const next = new Set(picked);
                if (e.target.checked) next.add(p.id);
                else next.delete(p.id);
                setPicked(next);
              }}
              aria-label={`Объединить «${p.name}»`}
            />
            <span className={cn(p.id === main && "font-semibold")}>{p.name}</span>
            <span className="text-xs text-muted-foreground">
              {p.recipe_count > 0 ? `в ${p.recipe_count} рец.` : "не используется"}
              {p.has_price && " · есть цена"}
            </span>
            {p.id === main ? (
              <span className="ml-auto rounded-full bg-primary/10 px-2 py-0.5 text-xs font-medium text-primary">главный</span>
            ) : (
              <button className="ml-auto text-xs text-primary hover:underline" onClick={() => setMain(p.id)}>
                сделать главным
              </button>
            )}
          </li>
        ))}
      </ul>
      <Button className="mt-3" size="sm" disabled={count === 0 || merge.isPending} onClick={() => merge.mutate()}>
        {merge.isPending && <Loader2 className="animate-spin" />}
        Объединить {count > 0 ? `${count} в «${mainName}»` : ""}
      </Button>
    </div>
  );
}

function MergeRow({ product, all, onDone }: { product: Product; all: Product[]; onDone: () => void }) {
  const queryClient = useQueryClient();
  const [into, setInto] = useState("");
  const merge = useMutation({
    mutationFn: () => api.catalog.mergeProduct(product.id, Number(into)),
    onSuccess: (p) => {
      queryClient.invalidateQueries({ queryKey: ["product-catalog"] });
      queryClient.invalidateQueries({ queryKey: ["products"] });
      queryClient.invalidateQueries({ queryKey: ["product-duplicates"] });
      invalidateCosts(queryClient);
      toast.success(`«${product.name}» объединён с «${p.name}»`);
      onDone();
    },
    onError: (e) => toast.error(e.message),
  });
  return (
    <div className="flex flex-wrap items-center gap-2 rounded-xl bg-muted/60 p-3 text-sm">
      <span>
        Заменить «{product.name}» во всех рецептах на
      </span>
      <div className="min-w-48 flex-1">
        <Select className="h-9" value={into} onChange={(e) => setInto(e.target.value)}>
          <option value="">выберите продукт…</option>
          {all
            .filter((p) => p.id !== product.id)
            .map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
        </Select>
      </div>
      <Button size="sm" disabled={!into || merge.isPending} onClick={() => merge.mutate()}>
        Объединить
      </Button>
      <Button size="sm" variant="ghost" onClick={onDone}>
        Отмена
      </Button>
    </div>
  );
}

export default function ProductsPage() {
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const [params, setParams] = useSearchParams();
  const [q, setQ] = useState(params.get("q") ?? "");
  const [filter, setFilter] = useState<"all" | "no-kbju" | "no-price">("all");
  const [open, setOpen] = useState<{ id: number; kind: "merge" | "price" } | null>(null);
  const toggle = (id: number, kind: "merge" | "price") =>
    setOpen(open?.id === id && open.kind === kind ? null : { id, kind });
  const catalog = useQuery({ queryKey: ["product-catalog"], queryFn: api.catalog.productCatalog });

  useEffect(() => {
    const t = setTimeout(() => setParams(q ? { q } : {}, { replace: true }), 300);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [q]);

  const update = useMutation({
    mutationFn: ({ id, patch }: { id: number; patch: ProductPatch }) => api.catalog.updateProduct(id, patch),
    onSuccess: (p) => {
      queryClient.setQueryData<Product[]>(["product-catalog"], (list) => list?.map((x) => (x.id === p.id ? p : x)));
      invalidateCosts(queryClient);
    },
    onError: (e) => toast.error(e.message),
  });
  const remove = useMutation({
    mutationFn: (id: number) => api.catalog.deleteProduct(id),
    onSuccess: (_, id) => {
      queryClient.setQueryData<Product[]>(["product-catalog"], (list) => list?.filter((x) => x.id !== id));
      queryClient.invalidateQueries({ queryKey: ["products"] });
    },
    onError: (e) => toast.error(e.message),
  });

  const all = catalog.data ?? [];
  const list = useMemo(() => {
    const needle = q.trim().toLowerCase().replace(/ё/g, "е");
    return all.filter(
      (p) =>
        (!needle || p.name.toLowerCase().replace(/ё/g, "е").includes(needle)) &&
        (filter === "all" || (filter === "no-kbju" ? p.kcal === null : p.price === null)),
    );
  }, [all, q, filter]);
  const emptyCount = all.filter((p) => p.kcal === null).length;
  const noPriceCount = all.filter((p) => p.price === null).length;

  return (
    <div className="grid gap-6">
      <div>
        <h1 className="title-display text-4xl sm:text-5xl">Продукты</h1>
        <p className="mt-2 max-w-2xl text-muted-foreground">
          КБЖУ на 100 г и цены. По ним считаются калорийность и себестоимость рецептов. Цену вводите как на
          ценнике — «220 ₽ за 180 г», остальное посчитается само. Справочник пополняется, когда вы добавляете рецепты.
        </p>
      </div>

      <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
        <div className="relative flex-1">
          <Search className="absolute top-1/2 left-4 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input className="h-11 rounded-full pl-11" placeholder="Найти продукт" value={q} onChange={(e) => setQ(e.target.value)} />
          {q && (
            <button className="absolute top-1/2 right-3 -translate-y-1/2 p-1 text-muted-foreground" onClick={() => setQ("")} aria-label="Очистить">
              <X className="size-4" />
            </button>
          )}
        </div>
        <div className="flex gap-2">
          <Chip active={filter === "all"} onClick={() => setFilter("all")}>
            Все {all.length}
          </Chip>
          <Chip active={filter === "no-kbju"} onClick={() => setFilter("no-kbju")}>
            Без КБЖУ {emptyCount}
          </Chip>
          <Chip active={filter === "no-price"} onClick={() => setFilter("no-price")}>
            Без цены {noPriceCount}
          </Chip>
        </div>
      </div>

      {user?.is_admin && <DuplicatesPanel />}

      {catalog.isLoading ? (
        <div className="flex justify-center py-16">
          <Loader2 className="size-6 animate-spin text-muted-foreground" />
        </div>
      ) : list.length === 0 ? (
        <p className="rounded-3xl bg-muted/60 px-6 py-14 text-center text-muted-foreground">
          {all.length === 0 ? "Продукты появятся здесь, когда вы добавите первый рецепт." : "Ничего не нашлось."}
        </p>
      ) : (
        <div className="overflow-hidden rounded-3xl border bg-card">
          <div className="overflow-x-auto">
            <table className="w-full min-w-[880px] text-sm">
              <thead>
                <tr className="border-b text-left text-xs text-muted-foreground">
                  <th className="px-5 py-3 font-medium">Продукт</th>
                  <th className="w-[150px] px-2 py-3 text-right font-medium" title="Последняя цена — нажмите, чтобы добавить новую">
                    Цена
                  </th>
                  {COLUMNS.map((c) => (
                    <th key={c.key} className="w-[88px] px-2 py-3 text-right font-medium" title={c.hint}>
                      {c.label}
                    </th>
                  ))}
                  <th className="w-24 px-3 py-3" />
                </tr>
              </thead>
              <tbody>
                {list.map((p) => (
                  <Fragment key={p.id}>
                    <tr className="border-b last:border-b-0 hover:bg-muted/40">
                      <td className="px-5 py-1.5">
                        <span className="font-medium">{p.name}</span>
                        <span className="ml-2 text-xs text-muted-foreground">
                          {p.recipe_count > 0 && `в ${p.recipe_count} рец.`}
                          {p.nutrition_source === "auto" && (p.recipe_count > 0 ? " · " : "") + "примерно"}
                        </span>
                      </td>
                      <td className="border-r px-1 py-1">
                        <PriceCell product={p} onClick={() => toggle(p.id, "price")} />
                      </td>
                      {COLUMNS.map((c) => (
                        <td key={c.key} className={cn("px-1 py-1", c.key === "piece_grams" && "border-l")}>
                          <NumCell product={p} k={c.key} onSave={(patch) => update.mutate({ id: p.id, patch })} />
                        </td>
                      ))}
                      <td className="px-3 py-1 text-right whitespace-nowrap">
                        {user?.is_admin && (
                          <>
                            <Button
                              size="icon"
                              variant="ghost"
                              className="size-8"
                              title="Объединить с другим продуктом"
                              aria-label="Объединить"
                              onClick={() => toggle(p.id, "merge")}
                            >
                              <Merge />
                            </Button>
                            <Button
                              size="icon"
                              variant="ghost"
                              className="size-8 hover:text-destructive"
                              title={p.recipe_count ? "Используется в рецептах — можно только объединить" : "Удалить"}
                              aria-label="Удалить"
                              disabled={p.recipe_count > 0}
                              onClick={() => confirm(`Удалить «${p.name}»?`) && remove.mutate(p.id)}
                            >
                              <Trash2 />
                            </Button>
                          </>
                        )}
                      </td>
                    </tr>
                    {open?.id === p.id && (
                      <tr className="border-b">
                        <td colSpan={COLUMNS.length + 3} className="px-4 py-3">
                          {open.kind === "merge" ? (
                            <MergeRow product={p} all={all} onDone={() => setOpen(null)} />
                          ) : (
                            <PriceRow product={p} onDone={() => setOpen(null)} />
                          )}
                        </td>
                      </tr>
                    )}
                  </Fragment>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
      <p className="text-xs text-muted-foreground">
        Пересчёт в граммы: ч. л. = 5 мл, ст. л. = 15 мл, стакан = 200 мл, умножается на плотность продукта. Для «шт»
        нужен вес одной штуки. «По вкусу» и «щепотка» в расчёт не входят. Себестоимость считается по последней
        цене продукта, а история цен сохраняется — по ней видно, как дорожают рецепты.
      </p>
    </div>
  );
}
