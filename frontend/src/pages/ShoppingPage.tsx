import { useEffect, useMemo, useState, type FormEvent } from "react";
import { Link } from "react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, ChefHat, CloudOff, Copy, Loader2, LogOut, Pencil, Plus, ShoppingBasket, Trash2, UserPlus, Users, X } from "lucide-react";
import { toast } from "sonner";
import { Avatar } from "@/components/Avatar";
import { PRICE_UNITS, PriceForm } from "@/components/PriceForm";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { api, type PriceUnit, type ShoppingItem, type ShoppingList } from "@/lib/api";
import { formatAmount, formatMoney } from "@/lib/format";
import { getLastList, setLastList } from "@/lib/shoppingList";
import { enqueue, onFlushed, overlay, pendingCount, tempId, useQueueVersion } from "@/lib/shoppingQueue";
import { cn } from "@/lib/utils";

// Общий список обновляется у всех: раз в несколько секунд, пока страница открыта
const POLL_MS = 5000;

function amountText(item: ShoppingItem) {
  if (item.unit === "по вкусу") return "по вкусу";
  if (item.amount === null) return item.unit;
  return `${formatAmount(item.amount, item.unit)} ${item.unit}`.trim();
}

// ---------- окно «Поделиться» ----------
function ShareDialog({ list, onClose }: { list: ShoppingList; onClose: () => void }) {
  const queryClient = useQueryClient();
  const users = useQuery({ queryKey: ["shopping-users"], queryFn: api.shopping.users });
  const [selected, setSelected] = useState<Set<number>>(new Set(list.members.map((m) => m.id)));
  const save = useMutation({
    mutationFn: () => api.shopping.setMembers(list.id, [...selected]),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["shopping-lists"] });
      toast.success(selected.size ? "Доступ обновлён" : "Список снова только ваш");
      onClose();
    },
    onError: (e) => toast.error(e.message),
  });

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/45 backdrop-blur-sm sm:items-center sm:p-4" role="dialog" aria-modal onClick={onClose}>
      <div
        className="w-full max-w-md rounded-t-3xl border bg-card p-6 pb-[max(1.5rem,env(safe-area-inset-bottom))] shadow-xl sm:rounded-3xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-semibold">Поделиться «{list.name}»</h2>
          <Button variant="ghost" size="icon" onClick={onClose} aria-label="Закрыть">
            <X />
          </Button>
        </div>
        <p className="mt-1 text-sm text-muted-foreground">
          Отмеченные пользователи увидят список и смогут добавлять и отмечать покупки.
        </p>
        <div className="mt-4 max-h-80 overflow-y-auto">
          {users.isLoading ? (
            <div className="flex justify-center py-8">
              <Loader2 className="size-5 animate-spin text-muted-foreground" />
            </div>
          ) : !users.data?.length ? (
            <p className="py-6 text-center text-sm text-muted-foreground">Других пользователей пока нет.</p>
          ) : (
            <ul className="grid gap-1">
              {users.data.map((u) => {
                const on = selected.has(u.id);
                return (
                  <li key={u.id}>
                    <button
                      className={cn("flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-left transition-colors", on ? "bg-accent" : "hover:bg-muted")}
                      onClick={() =>
                        setSelected((s) => {
                          const n = new Set(s);
                          if (n.has(u.id)) n.delete(u.id);
                          else n.add(u.id);
                          return n;
                        })
                      }
                    >
                      <Avatar src={u.avatar_url} name={u.name} />
                      <span className="flex-1 font-medium">{u.name}</span>
                      <span
                        className={cn(
                          "flex size-6 items-center justify-center rounded-full border-2",
                          on ? "border-primary bg-primary text-primary-foreground" : "border-input",
                        )}
                      >
                        {on && <Check className="size-3.5" strokeWidth={3} />}
                      </span>
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </div>
        <div className="mt-6 flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            Отмена
          </Button>
          <Button onClick={() => save.mutate()} disabled={save.isPending || users.isLoading}>
            {save.isPending && <Loader2 className="animate-spin" />} Сохранить
          </Button>
        </div>
      </div>
    </div>
  );
}

// ---------- строка списка ----------
/** Что подставить в форму цены: прошлую цену продукта, а если её нет — количество из списка. */
function priceDefaults(item: ShoppingItem) {
  if (item.price) return item.price;
  const unit = item.unit === "зубчик" || item.unit === "" ? "шт" : item.unit;
  if (item.amount && PRICE_UNITS.includes(unit as PriceUnit)) {
    return { package_amount: item.amount, package_unit: unit as PriceUnit };
  }
  return undefined;
}

function Row({
  item,
  onToggle,
  onRemove,
}: {
  item: ShoppingItem & { pending?: boolean };
  onToggle: (i: ShoppingItem) => void;
  onRemove: (id: number) => void;
}) {
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState(false);
  const save = useMutation({
    mutationFn: (data: Parameters<typeof api.shopping.setPrice>[1]) => api.shopping.setPrice(item.id, data),
    onSuccess: (saved) => {
      queryClient.invalidateQueries({ queryKey: ["shopping"] });
      queryClient.invalidateQueries({ queryKey: ["product-catalog"] });
      queryClient.invalidateQueries({ queryKey: ["product-prices"] });
      queryClient.invalidateQueries({ queryKey: ["recipe"] });
      queryClient.invalidateQueries({ queryKey: ["recipe-cost-history"] });
      toast.success(`Цена «${saved.name}» сохранена`);
      setEditing(false);
    },
    onError: (e) => toast.error(e.message),
  });

  return (
    <li className="group border-b last:border-b-0">
      <div className="flex items-center gap-3 px-4 sm:px-5">
        <button onClick={() => onToggle(item)} className="flex min-h-14 flex-1 items-center gap-3.5 py-2 text-left" aria-pressed={item.checked}>
          <span
            className={cn(
              "flex size-6 shrink-0 items-center justify-center rounded-full border-2 transition-colors",
              item.checked ? "border-success bg-success text-white" : "border-input group-hover:border-primary",
            )}
          >
            {item.checked && <Check className="size-3.5" strokeWidth={3} />}
          </span>
          <span className="min-w-0 flex-1">
            <span className={cn("block text-[15px] font-medium", item.checked && "text-muted-foreground line-through")}>{item.name}</span>
            {item.note && <span className="block truncate text-xs text-muted-foreground">{item.note}</span>}
            {item.pending && <span className="block text-xs text-muted-foreground">ждёт отправки</span>}
          </span>
          <span className="shrink-0 text-right">
            <span className={cn("block text-[15px] font-semibold tabular-nums", item.checked && "text-muted-foreground")}>
              {amountText(item)}
            </span>
            {item.est_cost != null && item.est_cost > 0 && (
              <span className="block text-xs text-muted-foreground tabular-nums">≈ {formatMoney(item.est_cost)}</span>
            )}
          </span>
        </button>
        {!item.pending && (
          <button
            onClick={() => setEditing(!editing)}
            className={cn(
              "inline-flex h-7 shrink-0 items-center gap-1 rounded-full px-2.5 text-xs font-medium whitespace-nowrap transition-colors",
              item.price
                ? "bg-accent text-accent-foreground hover:bg-accent/70"
                : "border border-dashed border-input text-muted-foreground hover:border-primary hover:text-primary",
              editing && "ring-2 ring-ring/40",
            )}
            aria-label={item.price ? `Изменить цену: ${item.name}` : `Указать цену: ${item.name}`}
            title={
              item.price
                ? `${formatMoney(item.price.price)} за ${String(item.price.package_amount).replace(".", ",")} ${item.price.package_unit} — изменить`
                : "Указать цену"
            }
          >
            {item.price ? (
              <span className="tabular-nums">{formatMoney(item.price.price)}</span>
            ) : (
              <>
                <Plus className="size-3" /> цена
              </>
            )}
          </button>
        )}
        <button
          onClick={() => onRemove(item.id)}
          className="rounded-md p-1.5 text-muted-foreground opacity-60 hover:text-destructive hover:opacity-100"
          aria-label={`Удалить ${item.name}`}
        >
          <X className="size-4" />
        </button>
      </div>
      {editing && (
        <div className="grid gap-2 bg-muted/50 px-4 py-3 sm:px-5">
          <p className="text-xs text-muted-foreground">
            {item.price
              ? `Прошлая цена от ${new Date(item.price.created_at).toLocaleDateString("ru-RU", { day: "numeric", month: "long" })} — поправьте, если изменилась`
              : "Цена с ценника — сохранится в справочнике и пересчитает себестоимость рецептов"}
          </p>
          <PriceForm
            initial={priceDefaults(item)}
            pending={save.isPending}
            onSubmit={(data) => save.mutate(data)}
            onCancel={() => setEditing(false)}
          />
        </div>
      )}
    </li>
  );
}

// ---------- страница ----------
export default function ShoppingPage() {
  const queryClient = useQueryClient();
  const lists = useQuery({ queryKey: ["shopping-lists"], queryFn: api.shopping.lists, refetchInterval: POLL_MS });
  const [activeId, setActiveId] = useState<number | null>(getLastList);
  const [text, setText] = useState("");
  const [sharing, setSharing] = useState(false);
  const [renaming, setRenaming] = useState<string | null>(null);
  const [creating, setCreating] = useState<string | null>(null);

  const all = lists.data ?? [];
  const active = all.find((l) => l.id === activeId) ?? all[0];
  const listId = active?.id;

  useEffect(() => {
    if (active) setLastList(active.id);
  }, [active]);

  const KEY = ["shopping", listId];
  const items = useQuery({
    queryKey: KEY,
    queryFn: () => api.shopping.items(listId!),
    enabled: listId !== undefined,
    refetchInterval: POLL_MS,
  });

  const refreshLists = () => queryClient.invalidateQueries({ queryKey: ["shopping-lists"] });

  // Все изменения пунктов идут через очередь: сразу видны на экране, а на сервер уходят,
  // как только есть связь. В магазине с плохим интернетом ничего не теряется.
  const queueVersion = useQueueVersion();
  useEffect(
    () =>
      onFlushed(() => {
        queryClient.invalidateQueries({ queryKey: ["shopping"] });
        refreshLists();
      }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  );
  const addItem = (t: string) => {
    enqueue({ kind: "add", listId: listId!, tempId: tempId(), text: t });
    setText("");
  };
  const toggleItem = (item: ShoppingItem) =>
    enqueue({ kind: "check", listId: listId!, itemId: item.id, checked: !item.checked });
  const removeItem = (id: number) => enqueue({ kind: "remove", listId: listId!, itemId: id });
  const clearItems = (checkedOnly: boolean) => enqueue({ kind: "clear", listId: listId!, checkedOnly });

  const createList = useMutation({
    mutationFn: (name: string) => api.shopping.createList(name),
    onSuccess: (l) => {
      refreshLists();
      setActiveId(l.id);
      setCreating(null);
    },
    onError: (e) => toast.error(e.message),
  });
  const renameList = useMutation({
    mutationFn: (name: string) => api.shopping.renameList(listId!, name),
    onSuccess: () => {
      refreshLists();
      setRenaming(null);
    },
    onError: (e) => toast.error(e.message),
  });
  const deleteList = useMutation({
    mutationFn: () => api.shopping.deleteList(listId!),
    onSuccess: () => {
      setActiveId(null);
      refreshLists();
    },
    onError: (e) => toast.error(e.message),
  });

  // eslint-disable-next-line react-hooks/exhaustive-deps
  const data = useMemo(() => (listId ? overlay(listId, items.data ?? []) : []), [listId, items.data, queueVersion]);
  const pending = listId ? pendingCount(listId) : 0;
  const todo = data.filter((i) => !i.checked);
  const done = data.filter((i) => i.checked);
  const sumCost = (items: ShoppingItem[]) => items.reduce((acc, i) => acc + (i.est_cost ?? 0), 0);
  const todoCost = sumCost(todo);
  const todoNoPrice = todo.filter((i) => i.est_cost == null).length;
  const doneCost = sumCost(done);
  const people = active ? [active.owner, ...active.members] : [];
  const shared = people.length > 1;

  const copy = async () => {
    const lines = todo.map((i) => `— ${i.name}${amountText(i) ? `: ${amountText(i)}` : ""}`);
    try {
      await navigator.clipboard.writeText(`${active?.name ?? "Купить"}:\n${lines.join("\n")}`);
      toast.success("Список скопирован");
    } catch {
      toast.error("Не удалось скопировать");
    }
  };

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (text.trim() && listId) addItem(text.trim());
  };

  return (
    <div className="mx-auto grid max-w-2xl gap-6">
      <h1 className="title-display text-4xl sm:text-5xl">Покупки</h1>

      {/* Вкладки списков */}
      <div className="-mx-4 flex gap-2 overflow-x-auto px-4 pb-1 [scrollbar-width:none] sm:mx-0 sm:flex-wrap sm:px-0">
        {all.map((l) => (
          <button
            key={l.id}
            onClick={() => setActiveId(l.id)}
            className={cn(
              "inline-flex h-9 shrink-0 items-center gap-1.5 rounded-full px-4 text-sm font-medium whitespace-nowrap transition-colors",
              l.id === listId ? "bg-foreground text-background" : "bg-card text-muted-foreground ring-1 ring-border hover:text-foreground",
            )}
          >
            {l.members.length > 0 && <Users className="size-3.5 opacity-70" />}
            {l.recipe_id !== null && <ChefHat className="size-3.5 opacity-70" />}
            {l.name}
            {l.todo > 0 && <span className="opacity-60 tabular-nums">{l.todo}</span>}
          </button>
        ))}
        {creating === null ? (
          <button
            onClick={() => setCreating("")}
            className="inline-flex h-9 shrink-0 items-center gap-1 rounded-full px-3.5 text-sm font-medium text-muted-foreground border border-dashed hover:text-foreground"
          >
            <Plus className="size-4" /> Новый список
          </button>
        ) : (
          <form
            className="flex shrink-0 items-center gap-1"
            onSubmit={(e) => {
              e.preventDefault();
              if (creating.trim()) createList.mutate(creating.trim());
            }}
          >
            <Input
              autoFocus
              className="h-9 w-44 rounded-full"
              placeholder="Название"
              value={creating}
              onChange={(e) => setCreating(e.target.value)}
              onKeyDown={(e) => e.key === "Escape" && setCreating(null)}
            />
            <Button type="submit" size="icon" className="size-9" disabled={!creating.trim()} aria-label="Создать">
              <Check />
            </Button>
            <Button type="button" size="icon" variant="ghost" className="size-9" onClick={() => setCreating(null)} aria-label="Отмена">
              <X />
            </Button>
          </form>
        )}
      </div>

      {active && (
        <>
          {/* Шапка списка: название, участники, действия */}
          <div className="flex flex-wrap items-center gap-3">
            {renaming === null ? (
              <div>
                <h2 className="text-xl font-semibold">{active.name}</h2>
                {active.recipe_id !== null && (
                  <Link to={`/recipes/${active.recipe_id}`} className="text-xs font-semibold text-primary hover:underline">
                    Список из рецепта — открыть рецепт
                  </Link>
                )}
              </div>
            ) : (
              <form
                className="flex items-center gap-1"
                onSubmit={(e) => {
                  e.preventDefault();
                  if (renaming.trim()) renameList.mutate(renaming.trim());
                }}
              >
                <Input autoFocus className="h-9 w-52" value={renaming} onChange={(e) => setRenaming(e.target.value)} />
                <Button type="submit" size="icon" className="size-9" aria-label="Сохранить">
                  <Check />
                </Button>
                <Button type="button" size="icon" variant="ghost" className="size-9" onClick={() => setRenaming(null)} aria-label="Отмена">
                  <X />
                </Button>
              </form>
            )}
            {shared && (
              <span className="flex -space-x-2" title={people.map((p) => p.name).join(", ")}>
                {people.slice(0, 5).map((p) => (
                  <Avatar key={p.id} src={p.avatar_url} name={p.name} className="size-7 text-[10px] ring-2 ring-background" />
                ))}
              </span>
            )}
            <div className="ml-auto flex items-center gap-1">
              {active.is_owner && (
                <Button variant="outline" size="sm" onClick={() => setSharing(true)}>
                  <UserPlus /> {shared ? "Доступ" : "Поделиться"}
                </Button>
              )}
              <Button variant="ghost" size="icon" className="size-8" onClick={() => setRenaming(active.name)} aria-label="Переименовать" title="Переименовать">
                <Pencil />
              </Button>
              {todo.length > 0 && (
                <Button variant="ghost" size="icon" className="size-8" onClick={copy} aria-label="Скопировать списком" title="Скопировать списком">
                  <Copy />
                </Button>
              )}
              {(all.length > 1 || !active.is_owner) && (
                <Button
                  variant="ghost"
                  size="icon"
                  className="size-8 hover:text-destructive"
                  title={active.is_owner ? "Удалить список" : "Выйти из списка"}
                  aria-label={active.is_owner ? "Удалить список" : "Выйти из списка"}
                  onClick={() =>
                    confirm(active.is_owner ? `Удалить список «${active.name}» вместе со всеми пунктами?` : `Выйти из списка «${active.name}»?`) &&
                    deleteList.mutate()
                  }
                >
                  {active.is_owner ? <Trash2 /> : <LogOut />}
                </Button>
              )}
            </div>
          </div>
          {(!active.is_owner || pending > 0) && (
            <p className="-mt-4 flex flex-wrap items-center gap-x-3 text-sm text-muted-foreground">
              {!active.is_owner && <span>Список {active.owner.name}</span>}
              {pending > 0 && (
                <span className="flex items-center gap-1.5 text-highlight-foreground">
                  <CloudOff className="size-3.5" /> Не отправлено: {pending} — уйдёт, когда появится связь
                </span>
              )}
            </p>
          )}

          <form onSubmit={submit} className="flex gap-2">
            <Input
              placeholder="Добавить: «2 кг картошки», «хлеб»"
              className="h-12 rounded-full px-5"
              value={text}
              onChange={(e) => setText(e.target.value)}
              enterKeyHint="done"
            />
            <Button type="submit" size="icon" className="size-12 shrink-0" disabled={!text.trim()} aria-label="Добавить">
              <Plus />
            </Button>
          </form>
        </>
      )}

      {lists.isLoading || (items.isLoading && listId !== undefined) ? (
        <div className="flex justify-center py-16">
          <Loader2 className="size-6 animate-spin text-muted-foreground" />
        </div>
      ) : data.length === 0 ? (
        <div className="flex flex-col items-center rounded-3xl bg-muted/60 px-6 py-16 text-center">
          <div className="rounded-2xl bg-card p-4">
            <ShoppingBasket className="size-8 text-primary" strokeWidth={1.5} />
          </div>
          <h2 className="mt-5 text-xl font-semibold">Список пуст</h2>
          <p className="mt-2 max-w-sm text-sm text-muted-foreground">
            Добавьте продукты строкой выше или откройте рецепт и нажмите «В список покупок» — одинаковые продукты сложатся.
          </p>
          <Button asChild variant="outline" className="mt-6">
            <Link to="/">К рецептам</Link>
          </Button>
        </div>
      ) : (
        <>
          {todo.length > 0 && todoCost > 0 && (
            <p className="-mb-3 px-1 text-sm text-muted-foreground">
              Осталось купить примерно на <span className="font-semibold text-foreground tabular-nums">{formatMoney(todoCost)}</span>
              {todoNoPrice > 0 && ` · без цены: ${todoNoPrice}`}
            </p>
          )}
          {todo.length > 0 ? (
            <ul className="overflow-hidden rounded-3xl border bg-card">
              {todo.map((i) => (
                <Row key={i.id} item={i} onToggle={toggleItem} onRemove={removeItem} />
              ))}
            </ul>
          ) : (
            <p className="rounded-3xl bg-muted/60 px-6 py-8 text-center font-medium">Всё куплено</p>
          )}

          {done.length > 0 && (
            <section className="grid gap-3">
              <div className="flex items-center justify-between">
                <h2 className="text-sm font-semibold text-muted-foreground">
                  Куплено: {done.length}
                  {doneCost > 0 && <span className="font-normal tabular-nums"> · ≈ {formatMoney(doneCost)}</span>}
                </h2>
                <Button variant="ghost" size="sm" onClick={() => clearItems(true)}>
                  <Trash2 /> Очистить купленное
                </Button>
              </div>
              <ul className="overflow-hidden rounded-3xl border bg-card/60">
                {done.map((i) => (
                  <Row key={i.id} item={i} onToggle={toggleItem} onRemove={removeItem} />
                ))}
              </ul>
            </section>
          )}

          <div className="flex justify-center">
            <Button
              variant="ghost"
              size="sm"
              className="text-muted-foreground hover:text-destructive"
              onClick={() => confirm("Убрать все пункты из этого списка?") && clearItems(false)}
            >
              Очистить список
            </Button>
          </div>
        </>
      )}

      {sharing && active && <ShareDialog list={active} onClose={() => setSharing(false)} />}
    </div>
  );
}
