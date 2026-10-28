import { useState, type FormEvent } from "react";
import { Link } from "react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Copy, Loader2, Plus, ShoppingBasket, Trash2, X } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { api, type ShoppingItem } from "@/lib/api";
import { formatAmount } from "@/lib/format";
import { cn } from "@/lib/utils";

const KEY = ["shopping"];

function amountText(item: ShoppingItem) {
  if (item.unit === "по вкусу") return "по вкусу";
  if (item.amount === null) return item.unit;
  return `${formatAmount(item.amount, item.unit)} ${item.unit}`.trim();
}

export default function ShoppingPage() {
  const queryClient = useQueryClient();
  const list = useQuery({ queryKey: KEY, queryFn: api.shopping.list });
  const [text, setText] = useState("");

  const setList = (items: ShoppingItem[]) => queryClient.setQueryData(KEY, items);

  const add = useMutation({
    mutationFn: (t: string) => api.shopping.addText(t),
    onSuccess: (items) => {
      setList(items);
      setText("");
    },
    onError: (e) => toast.error(e.message),
  });
  const toggle = useMutation({
    mutationFn: (item: ShoppingItem) => api.shopping.update(item.id, { checked: !item.checked }),
    onMutate: (item) => {
      // Мгновенная реакция: в магазине ждать сервер некогда
      queryClient.setQueryData<ShoppingItem[]>(KEY, (l) =>
        l?.map((x) => (x.id === item.id ? { ...x, checked: !x.checked } : x)),
      );
    },
    onError: (e) => {
      toast.error(e.message);
      queryClient.invalidateQueries({ queryKey: KEY });
    },
  });
  const remove = useMutation({
    mutationFn: (id: number) => api.shopping.remove(id),
    onMutate: (id) => queryClient.setQueryData<ShoppingItem[]>(KEY, (l) => l?.filter((x) => x.id !== id)),
    onError: () => queryClient.invalidateQueries({ queryKey: KEY }),
  });
  const clear = useMutation({
    mutationFn: (checkedOnly: boolean) => api.shopping.clear(checkedOnly),
    onSuccess: setList,
    onError: (e) => toast.error(e.message),
  });

  const items = list.data ?? [];
  const todo = items.filter((i) => !i.checked);
  const done = items.filter((i) => i.checked);

  const copy = async () => {
    const lines = todo.map((i) => `— ${i.name}${amountText(i) ? `: ${amountText(i)}` : ""}`);
    try {
      await navigator.clipboard.writeText(`Купить:\n${lines.join("\n")}`);
      toast.success("Список скопирован");
    } catch {
      toast.error("Не удалось скопировать");
    }
  };

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (text.trim()) add.mutate(text.trim());
  };

  const Row = ({ item }: { item: ShoppingItem }) => (
    <li className="group flex items-center gap-3 border-b px-4 last:border-b-0 sm:px-5">
      <button
        onClick={() => toggle.mutate(item)}
        className="flex min-h-14 flex-1 items-center gap-3.5 py-2 text-left"
        aria-pressed={item.checked}
      >
        <span
          className={cn(
            "flex size-6 shrink-0 items-center justify-center rounded-full border-2 transition-colors",
            item.checked ? "border-success bg-success text-white" : "border-input group-hover:border-primary",
          )}
        >
          {item.checked && <Check className="size-3.5" strokeWidth={3} />}
        </span>
        <span className="min-w-0 flex-1">
          <span className={cn("block text-[15px] font-medium", item.checked && "text-muted-foreground line-through")}>
            {item.name}
          </span>
          {item.note && <span className="block truncate text-xs text-muted-foreground">{item.note}</span>}
        </span>
        <span className={cn("shrink-0 text-[15px] font-semibold tabular-nums", item.checked && "text-muted-foreground")}>
          {amountText(item)}
        </span>
      </button>
      <button
        onClick={() => remove.mutate(item.id)}
        className="rounded-md p-1.5 text-muted-foreground opacity-60 hover:text-destructive hover:opacity-100"
        aria-label={`Удалить ${item.name}`}
      >
        <X className="size-4" />
      </button>
    </li>
  );

  return (
    <div className="mx-auto grid max-w-2xl gap-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <h1 className="title-display text-4xl sm:text-5xl">Покупки</h1>
        {todo.length > 0 && (
          <Button variant="outline" size="sm" onClick={copy}>
            <Copy /> Скопировать списком
          </Button>
        )}
      </div>

      <form onSubmit={submit} className="flex gap-2">
        <Input
          placeholder="Добавить: «2 кг картошки», «хлеб»"
          className="h-12 rounded-full px-5"
          value={text}
          onChange={(e) => setText(e.target.value)}
          enterKeyHint="done"
        />
        <Button type="submit" size="icon" className="size-12 shrink-0" disabled={!text.trim() || add.isPending} aria-label="Добавить">
          {add.isPending ? <Loader2 className="animate-spin" /> : <Plus />}
        </Button>
      </form>

      {list.isLoading ? (
        <div className="flex justify-center py-16">
          <Loader2 className="size-6 animate-spin text-muted-foreground" />
        </div>
      ) : items.length === 0 ? (
        <div className="flex flex-col items-center rounded-3xl bg-muted/60 px-6 py-16 text-center">
          <div className="rounded-2xl bg-card p-4">
            <ShoppingBasket className="size-8 text-primary" strokeWidth={1.5} />
          </div>
          <h2 className="mt-5 text-xl font-semibold">Список пуст</h2>
          <p className="mt-2 max-w-sm text-sm text-muted-foreground">
            Откройте рецепт и нажмите «В список покупок» — ингредиенты добавятся сюда, одинаковые сложатся.
          </p>
          <Button asChild variant="outline" className="mt-6">
            <Link to="/">К рецептам</Link>
          </Button>
        </div>
      ) : (
        <>
          {todo.length > 0 ? (
            <ul className="overflow-hidden rounded-3xl border bg-card">
              {todo.map((i) => (
                <Row key={i.id} item={i} />
              ))}
            </ul>
          ) : (
            <p className="rounded-3xl bg-muted/60 px-6 py-8 text-center font-medium">Всё куплено</p>
          )}

          {done.length > 0 && (
            <section className="grid gap-3">
              <div className="flex items-center justify-between">
                <h2 className="text-sm font-semibold text-muted-foreground">Куплено · {done.length}</h2>
                <Button variant="ghost" size="sm" onClick={() => clear.mutate(true)} disabled={clear.isPending}>
                  <Trash2 /> Очистить купленное
                </Button>
              </div>
              <ul className="overflow-hidden rounded-3xl border bg-card/60">
                {done.map((i) => (
                  <Row key={i.id} item={i} />
                ))}
              </ul>
            </section>
          )}

          <div className="flex justify-center">
            <Button
              variant="ghost"
              size="sm"
              className="text-muted-foreground hover:text-destructive"
              onClick={() => confirm("Очистить весь список?") && clear.mutate(false)}
            >
              Очистить весь список
            </Button>
          </div>
        </>
      )}
    </div>
  );
}
