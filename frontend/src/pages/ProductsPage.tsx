import { Fragment, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, Merge, Search, Trash2, X } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Chip } from "@/components/ui/chip";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { api, type Product, type ProductPatch } from "@/lib/api";
import { useAuth } from "@/lib/auth";
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

function MergeRow({ product, all, onDone }: { product: Product; all: Product[]; onDone: () => void }) {
  const queryClient = useQueryClient();
  const [into, setInto] = useState("");
  const merge = useMutation({
    mutationFn: () => api.catalog.mergeProduct(product.id, Number(into)),
    onSuccess: (p) => {
      queryClient.invalidateQueries({ queryKey: ["product-catalog"] });
      queryClient.invalidateQueries({ queryKey: ["products"] });
      queryClient.invalidateQueries({ queryKey: ["recipe"] });
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
  const [onlyEmpty, setOnlyEmpty] = useState(false);
  const [merging, setMerging] = useState<number | null>(null);
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
      queryClient.invalidateQueries({ queryKey: ["recipe"] });
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
        (!needle || p.name.toLowerCase().replace(/ё/g, "е").includes(needle)) && (!onlyEmpty || p.kcal === null),
    );
  }, [all, q, onlyEmpty]);
  const emptyCount = all.filter((p) => p.kcal === null).length;

  return (
    <div className="grid gap-6">
      <div>
        <h1 className="title-display text-4xl sm:text-5xl">Продукты</h1>
        <p className="mt-2 max-w-2xl text-muted-foreground">
          КБЖУ на 100 г. По ним считается калорийность рецептов. Для частых продуктов значения заполнены
          примерно, их можно поправить. Справочник пополняется сам, когда вы добавляете рецепты.
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
          <Chip active={!onlyEmpty} onClick={() => setOnlyEmpty(false)}>
            Все {all.length}
          </Chip>
          <Chip active={onlyEmpty} onClick={() => setOnlyEmpty(true)}>
            Без КБЖУ {emptyCount}
          </Chip>
        </div>
      </div>

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
            <table className="w-full min-w-[720px] text-sm">
              <thead>
                <tr className="border-b text-left text-xs text-muted-foreground">
                  <th className="px-5 py-3 font-medium">Продукт</th>
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
                              onClick={() => setMerging(merging === p.id ? null : p.id)}
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
                    {merging === p.id && (
                      <tr className="border-b">
                        <td colSpan={COLUMNS.length + 2} className="px-4 py-3">
                          <MergeRow product={p} all={all} onDone={() => setMerging(null)} />
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
        нужен вес одной штуки. «По вкусу» и «щепотка» в расчёт не входят.
      </p>
    </div>
  );
}
