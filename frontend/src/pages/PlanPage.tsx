import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  CalendarDays,
  Check,
  ChevronLeft,
  ChevronRight,
  Dices,
  Loader2,
  Minus,
  Plus,
  Search,
  ShoppingBasket,
  StickyNote,
  Trash2,
  Users,
  UtensilsCrossed,
} from "lucide-react";
import { toast } from "sonner";
import { Avatar } from "@/components/Avatar";
import { Button } from "@/components/ui/button";
import { Chip } from "@/components/ui/chip";
import { Input } from "@/components/ui/input";
import { Sheet } from "@/components/ui/sheet";
import { Switch } from "@/components/ui/switch";
import { api, type MealSlot, type Person, type PlanEntry, type RecipeListItem } from "@/lib/api";
import { SLOTS, WEEKDAYS_FULL, addDays, dayLabel, iso, parseIso, rangeLabel, relativeDay, weekStart } from "@/lib/dates";
import { formatMinutes, plural } from "@/lib/format";
import { useOnline } from "@/lib/offline";
import { getLastList, setLastList } from "@/lib/shoppingList";
import { cn } from "@/lib/utils";

function Stepper({ value, onChange, small }: { value: number; onChange: (v: number) => void; small?: boolean }) {
  return (
    <div className={cn("flex items-center rounded-full bg-muted", small ? "gap-0 p-0.5" : "gap-1 p-1")}>
      <button
        type="button"
        className={cn("flex items-center justify-center rounded-full hover:bg-card disabled:opacity-40", small ? "size-7" : "size-8")}
        onClick={() => onChange(Math.max(1, value - 1))}
        disabled={value <= 1}
        aria-label="Меньше порций"
      >
        <Minus className="size-3.5" />
      </button>
      <span className={cn("text-center font-semibold tabular-nums", small ? "min-w-[3.25rem] text-xs" : "min-w-[4.5rem] text-sm")}>
        {value} {small ? "порц." : plural(value, "порция", "порции", "порций")}
      </span>
      <button
        type="button"
        className={cn("flex items-center justify-center rounded-full hover:bg-card", small ? "size-7" : "size-8")}
        onClick={() => onChange(Math.min(100, value + 1))}
        aria-label="Больше порций"
      >
        <Plus className="size-3.5" />
      </button>
    </div>
  );
}

// ---------- добавление блюда ----------
function AddEntrySheet({
  day,
  ownerId,
  onClose,
}: {
  day: string;
  ownerId?: number;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const [slot, setSlot] = useState<MealSlot>(() => {
    const h = new Date().getHours();
    return day === iso(new Date()) && h < 11 ? "breakfast" : day === iso(new Date()) && h < 15 ? "lunch" : "dinner";
  });
  const [q, setQ] = useState("");
  const [debounced, setDebounced] = useState("");
  const [favorites, setFavorites] = useState(false);
  const [note, setNote] = useState("");
  const [picked, setPicked] = useState<RecipeListItem | null>(null);
  const [servings, setServings] = useState(2);
  const [rolling, setRolling] = useState(false);

  useEffect(() => {
    const t = setTimeout(() => setDebounced(q.trim()), 250);
    return () => clearTimeout(t);
  }, [q]);

  const results = useQuery({
    queryKey: ["recipes", "pick", debounced, favorites],
    queryFn: () => api.recipes.list({ q: debounced || undefined, favorites, limit: 30 }),
    placeholderData: keepPreviousData,
  });

  const add = useMutation({
    mutationFn: () =>
      api.plan.add({ day, slot, recipe_id: picked?.id ?? null, servings, note: picked ? "" : note.trim(), owner_id: ownerId }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["plan"] });
      onClose();
    },
    onError: (e) => toast.error(e.message),
  });

  const pick = (r: RecipeListItem) => {
    setPicked(r);
    setServings(r.servings);
  };

  async function roll() {
    setRolling(true);
    try {
      pick(await api.recipes.random({ favorites, exclude: picked ? String(picked.id) : undefined }));
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setRolling(false);
    }
  }

  const d = parseIso(day);
  return (
    <Sheet
      title={`${relativeDay(d) ?? WEEKDAYS_FULL[(d.getDay() + 6) % 7]}, ${dayLabel(d)}`}
      onClose={onClose}
      className="sm:max-w-lg"
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Отмена
          </Button>
          <Button onClick={() => add.mutate()} disabled={add.isPending || (!picked && !note.trim())}>
            {add.isPending && <Loader2 className="animate-spin" />} Добавить
          </Button>
        </>
      }
    >
      <div className="flex flex-wrap gap-2">
        {SLOTS.map((s) => (
          <Chip key={s.id} active={slot === s.id} onClick={() => setSlot(s.id)}>
            {s.label}
          </Chip>
        ))}
      </div>

      {picked ? (
        <div className="mt-4 flex items-center gap-3 rounded-2xl border bg-muted/40 p-3">
          <div className="size-14 shrink-0 overflow-hidden rounded-xl bg-muted">
            {picked.thumb_url ? (
              <img src={picked.thumb_url} alt="" className="h-full w-full object-cover" />
            ) : (
              <UtensilsCrossed className="m-4 size-6 text-primary/40" />
            )}
          </div>
          <div className="min-w-0 flex-1">
            <p className="truncate font-semibold">{picked.title}</p>
            <button className="text-xs font-semibold text-primary hover:underline" onClick={() => setPicked(null)}>
              Выбрать другое
            </button>
          </div>
        </div>
      ) : (
        <>
          <div className="mt-4 flex gap-2">
            <div className="relative flex-1">
              <Search className="absolute top-1/2 left-3.5 size-4 -translate-y-1/2 text-muted-foreground" />
              <Input className="pl-10" placeholder="Найти рецепт" value={q} onChange={(e) => setQ(e.target.value)} type="search" />
            </div>
            <Button variant="outline" size="icon" className="size-11 shrink-0" onClick={roll} disabled={rolling} title="Случайный рецепт" aria-label="Случайный рецепт">
              {rolling ? <Loader2 className="animate-spin" /> : <Dices />}
            </Button>
          </div>
          <label className="mt-2 flex items-center gap-2 text-sm text-muted-foreground">
            <Switch checked={favorites} onCheckedChange={setFavorites} /> Только избранное
          </label>
          <ul className="mt-3 grid max-h-[38svh] gap-1 overflow-y-auto">
            {results.data?.items.map((r) => (
              <li key={r.id}>
                <button
                  onClick={() => pick(r)}
                  className="flex w-full items-center gap-3 rounded-xl px-2 py-2 text-left transition-colors hover:bg-muted"
                >
                  <div className="size-11 shrink-0 overflow-hidden rounded-lg bg-muted">
                    {r.thumb_url && <img src={r.thumb_url} alt="" loading="lazy" className="h-full w-full object-cover" />}
                  </div>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-[15px] font-medium">{r.title}</span>
                    <span className="block truncate text-xs text-muted-foreground">
                      {[r.category?.name, formatMinutes(r.total_minutes)].filter(Boolean).join(" · ")}
                    </span>
                  </span>
                </button>
              </li>
            ))}
            {results.data && results.data.items.length === 0 && (
              <li className="py-4 text-center text-sm text-muted-foreground">Ничего не нашлось</li>
            )}
          </ul>
          <div className="mt-3 border-t pt-3">
            <p className="mb-2 flex items-center gap-1.5 text-sm font-semibold">
              <StickyNote className="size-4 text-muted-foreground" /> Или без рецепта
            </p>
            <Input
              placeholder="Пельмени, в гостях, доедаем суп…"
              maxLength={200}
              value={note}
              onChange={(e) => setNote(e.target.value)}
            />
          </div>
        </>
      )}

      {picked && (
        <div className="mt-4 flex items-center justify-between">
          <span className="text-sm font-semibold">Порций</span>
          <Stepper value={servings} onChange={setServings} />
        </div>
      )}
    </Sheet>
  );
}

// ---------- блюдо: порции, перенос, удаление ----------
function EntrySheet({ entry, days, onClose }: { entry: PlanEntry; days: Date[]; onClose: () => void }) {
  const queryClient = useQueryClient();
  const [servings, setServings] = useState(entry.servings);
  const [day, setDay] = useState(entry.day);
  const [slot, setSlot] = useState<MealSlot>(entry.slot);
  const done = () => {
    queryClient.invalidateQueries({ queryKey: ["plan"] });
    onClose();
  };
  const save = useMutation({
    mutationFn: () => api.plan.update(entry.id, { servings, day, slot }),
    onSuccess: done,
    onError: (e) => toast.error(e.message),
  });
  const remove = useMutation({
    mutationFn: () => api.plan.remove(entry.id),
    onSuccess: done,
    onError: (e) => toast.error(e.message),
  });

  return (
    <Sheet
      title={entry.recipe?.title ?? entry.note}
      onClose={onClose}
      footer={
        <>
          <Button
            variant="ghost"
            className="mr-auto text-destructive hover:text-destructive"
            onClick={() => remove.mutate()}
            disabled={remove.isPending}
          >
            <Trash2 /> Убрать
          </Button>
          <Button onClick={() => save.mutate()} disabled={save.isPending}>
            {save.isPending && <Loader2 className="animate-spin" />} Сохранить
          </Button>
        </>
      }
    >
      {entry.recipe && (
        <>
          <div className="flex items-center justify-between">
            <span className="text-sm font-semibold">Порций</span>
            <Stepper value={servings} onChange={setServings} />
          </div>
          <Link to={`/recipes/${entry.recipe.id}`} className="mt-3 inline-block text-sm font-semibold text-primary hover:underline">
            Открыть рецепт
          </Link>
        </>
      )}
      <p className="mt-4 mb-2 text-sm font-semibold">Перенести</p>
      <div className="flex flex-wrap gap-1.5">
        {days.map((d) => (
          <Chip key={iso(d)} active={iso(d) === day} onClick={() => setDay(iso(d))} className="h-8 px-3">
            {WEEKDAYS_FULL[(d.getDay() + 6) % 7].slice(0, 2)}, {d.getDate()}
          </Chip>
        ))}
      </div>
      <div className="mt-3 flex flex-wrap gap-1.5">
        {SLOTS.map((s) => (
          <Chip key={s.id} active={slot === s.id} onClick={() => setSlot(s.id)} className="h-8 px-3">
            {s.label}
          </Chip>
        ))}
      </div>
    </Sheet>
  );
}

// ---------- в список покупок ----------
function ToShoppingSheet({
  start,
  end,
  ownerId,
  count,
  onClose,
}: {
  start: Date;
  end: Date;
  ownerId?: number;
  count: number;
  onClose: () => void;
}) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const lists = useQuery({ queryKey: ["shopping-lists"], queryFn: api.shopping.lists });
  const [listId, setListId] = useState<number | null>(getLastList);
  const target = lists.data?.find((l) => l.id === listId) ?? lists.data?.[0];
  const today = new Date();
  const includesToday = iso(today) >= iso(start) && iso(today) <= iso(end);
  const [fromToday, setFromToday] = useState(includesToday);
  const [skipPantry, setSkipPantry] = useState(true);

  const send = useMutation({
    mutationFn: () =>
      api.plan.toShopping({
        list_id: target!.id,
        start: fromToday && includesToday ? iso(today) : iso(start),
        end: iso(end),
        owner_id: ownerId,
        skip_pantry: skipPantry,
      }),
    onSuccess: (r) => {
      setLastList(target!.id);
      queryClient.setQueryData(["shopping", target!.id], r.items);
      queryClient.invalidateQueries({ queryKey: ["shopping-lists"] });
      const parts: string[] = [];
      if (r.added) parts.push(`добавлено ${r.added}`);
      if (r.merged) parts.push(`сложено ${r.merged}`);
      toast.success(`В списке «${target!.name}»`, {
        description: parts.join(", ") || "Нечего добавлять",
        action: { label: "Открыть", onClick: () => navigate("/shopping") },
      });
      onClose();
    },
    onError: (e) => toast.error(e.message),
  });

  return (
    <Sheet
      title="Продукты на неделю"
      onClose={onClose}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Отмена
          </Button>
          <Button onClick={() => send.mutate()} disabled={send.isPending || !target}>
            {send.isPending ? <Loader2 className="animate-spin" /> : <ShoppingBasket />} Добавить
          </Button>
        </>
      }
    >
      <p className="text-sm text-muted-foreground">
        Ингредиенты всех блюд ({count}) — с учётом порций. Одинаковые продукты сложатся: 200 г + 300 г муки = 500 г.
      </p>
      {lists.data && lists.data.length > 1 && (
        <>
          <p className="mt-4 mb-2 text-sm font-semibold">В список</p>
          <div className="flex flex-wrap gap-2">
            {lists.data.map((l) => (
              <Chip key={l.id} active={target?.id === l.id} onClick={() => setListId(l.id)}>
                {l.name}
              </Chip>
            ))}
          </div>
        </>
      )}
      <div className="mt-4 grid gap-2">
        {includesToday && (
          <label className="flex cursor-pointer items-center justify-between gap-3 rounded-xl bg-muted/60 px-4 py-3">
            <span className="text-sm font-medium">Только с сегодняшнего дня</span>
            <Switch checked={fromToday} onCheckedChange={setFromToday} />
          </label>
        )}
        <label className="flex cursor-pointer items-center justify-between gap-3 rounded-xl bg-muted/60 px-4 py-3">
          <span>
            <span className="block text-sm font-medium">Не добавлять то, что есть дома</span>
            <Link to="/pantry" className="text-xs text-primary hover:underline" onClick={onClose}>
              Что есть дома
            </Link>
          </span>
          <Switch checked={skipPantry} onCheckedChange={setSkipPantry} />
        </label>
      </div>
    </Sheet>
  );
}

// ---------- доступ к меню ----------
function MembersSheet({ members, onClose }: { members: Person[]; onClose: () => void }) {
  const queryClient = useQueryClient();
  const users = useQuery({ queryKey: ["share-users"], queryFn: api.shopping.users });
  const [selected, setSelected] = useState(() => new Set(members.map((m) => m.id)));
  const save = useMutation({
    mutationFn: () => api.plan.setMembers([...selected]),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["plan"] });
      toast.success(selected.size ? "Доступ обновлён" : "Меню снова только ваше");
      onClose();
    },
    onError: (e) => toast.error(e.message),
  });
  return (
    <Sheet
      title="Общее меню"
      onClose={onClose}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Отмена
          </Button>
          <Button onClick={() => save.mutate()} disabled={save.isPending || users.isLoading}>
            {save.isPending && <Loader2 className="animate-spin" />} Сохранить
          </Button>
        </>
      }
    >
      <p className="text-sm text-muted-foreground">Отмеченные увидят ваше меню и смогут его менять — удобно планировать всей семьёй.</p>
      <ul className="mt-3 grid gap-1">
        {users.data?.map((u) => {
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
        {users.data?.length === 0 && <li className="py-6 text-center text-sm text-muted-foreground">Других пользователей пока нет.</li>}
      </ul>
    </Sheet>
  );
}

// ---------- страница ----------
export default function PlanPage() {
  const [params, setParams] = useSearchParams();
  const online = useOnline();
  const anchor = params.get("date") ? parseIso(params.get("date")!) : new Date();
  const start = weekStart(anchor);
  const end = addDays(start, 6);
  const days = useMemo(() => Array.from({ length: 7 }, (_, i) => addDays(start, i)), [iso(start)]); // eslint-disable-line react-hooks/exhaustive-deps
  const ownerParam = params.get("owner") ? Number(params.get("owner")) : undefined;

  const owners = useQuery({ queryKey: ["plan-owners"], queryFn: api.plan.owners });
  const plan = useQuery({
    queryKey: ["plan", iso(start), ownerParam],
    queryFn: () => api.plan.get(iso(start), 7, ownerParam),
    placeholderData: keepPreviousData,
  });

  const [adding, setAdding] = useState<string | null>(null);
  const [editing, setEditing] = useState<PlanEntry | null>(null);
  const [shopping, setShopping] = useState(false);
  const [sharing, setSharing] = useState(false);

  const setParam = (key: string, value: string | null) => {
    const next = new URLSearchParams(params);
    if (value === null) next.delete(key);
    else next.set(key, value);
    setParams(next, { replace: true });
  };
  const shiftWeek = (n: number) => setParam("date", iso(addDays(start, n * 7)));

  const byDay = useMemo(() => {
    const map = new Map<string, PlanEntry[]>();
    for (const e of plan.data?.entries ?? []) {
      const list = map.get(e.day) ?? [];
      list.push(e);
      map.set(e.day, list);
    }
    return map;
  }, [plan.data]);

  const entries = plan.data?.entries ?? [];
  const withRecipe = entries.filter((e) => e.recipe);
  const thisWeek = iso(weekStart(new Date())) === iso(start);
  const canEdit = online;

  // На телефоне неделя длинная — сразу показываем сегодняшний день
  const loaded = Boolean(plan.data);
  useEffect(() => {
    if (!loaded || !thisWeek || window.innerWidth >= 768) return;
    const el = document.getElementById(`day-${iso(new Date())}`);
    if (el && (new Date().getDay() + 6) % 7 >= 2) el.scrollIntoView({ block: "start" });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loaded]);

  return (
    <div className="grid gap-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="title-display text-4xl sm:text-5xl">Меню</h1>
          <p className="mt-2 text-muted-foreground">
            {entries.length
              ? `${entries.length} ${plural(entries.length, "блюдо", "блюда", "блюд")} на неделю`
              : "Распланируйте, что готовить, — список покупок соберётся сам"}
          </p>
        </div>
        <div className="flex gap-2">
          {plan.data?.is_owner && (
            <Button variant="outline" onClick={() => setSharing(true)} disabled={!online}>
              <Users /> {plan.data.members.length ? `Общее · ${plan.data.members.length + 1}` : "Поделиться"}
            </Button>
          )}
          <Button onClick={() => setShopping(true)} disabled={!withRecipe.length || !online}>
            <ShoppingBasket /> В список покупок
          </Button>
        </div>
      </div>

      {owners.data && owners.data.owners.length > 1 && (
        <div className="-mx-4 flex gap-2 overflow-x-auto px-4 [scrollbar-width:none] sm:mx-0 sm:px-0">
          {owners.data.owners.map((o, i) => {
            const active = (ownerParam ?? owners.data.owners[0].id) === o.id;
            return (
              <Chip key={o.id} active={active} onClick={() => setParam("owner", i === 0 ? null : String(o.id))}>
                <Avatar src={o.avatar_url} name={o.name} className="-ml-2 size-6 text-[10px]" />
                {i === 0 ? "Моё меню" : o.name}
              </Chip>
            );
          })}
        </div>
      )}

      {/* Неделя */}
      <div className="flex items-center gap-2">
        <Button variant="outline" size="icon" onClick={() => shiftWeek(-1)} aria-label="Предыдущая неделя">
          <ChevronLeft />
        </Button>
        <div className="min-w-0 flex-1 text-center">
          <p className="font-semibold">{rangeLabel(start, end)}</p>
          {!thisWeek && (
            <button className="text-xs font-semibold text-primary hover:underline" onClick={() => setParam("date", null)}>
              К текущей неделе
            </button>
          )}
          {thisWeek && <p className="text-xs text-muted-foreground">эта неделя</p>}
        </div>
        <Button variant="outline" size="icon" onClick={() => shiftWeek(1)} aria-label="Следующая неделя">
          <ChevronRight />
        </Button>
      </div>

      {plan.isLoading ? (
        <div className="flex justify-center py-20">
          <Loader2 className="size-6 animate-spin text-muted-foreground" />
        </div>
      ) : plan.isError ? (
        <p className="py-10 text-center text-muted-foreground">Не удалось загрузить меню: {(plan.error as Error).message}</p>
      ) : (
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {days.map((d) => {
            const key = iso(d);
            const list = byDay.get(key) ?? [];
            const rel = relativeDay(d);
            const isToday = rel === "Сегодня";
            const past = key < iso(new Date());
            const kcal = list.reduce((n, e) => n + (e.recipe?.kcal_per_serving ?? 0), 0);
            return (
              <section
                key={key}
                id={`day-${key}`}
                className={cn("scroll-mt-20",
                  "flex flex-col rounded-3xl border bg-card p-4",
                  isToday && "border-primary/50 ring-4 ring-primary/10",
                  past && !isToday && "opacity-70",
                )}
              >
                <header className="flex items-center gap-2">
                  <div className="min-w-0 flex-1">
                    <h2 className="flex items-center gap-2 font-semibold">
                      {WEEKDAYS_FULL[(d.getDay() + 6) % 7]}
                      {rel && (
                        <span className={cn("rounded-full px-2 py-0.5 text-[11px] font-semibold", isToday ? "bg-primary text-primary-foreground" : "bg-muted text-muted-foreground")}>
                          {rel.toLowerCase()}
                        </span>
                      )}
                    </h2>
                    <p className="text-xs text-muted-foreground">
                      {dayLabel(d)}
                      {kcal > 0 && ` · ≈ ${kcal} ккал на человека`}
                    </p>
                  </div>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="size-9"
                    onClick={() => setAdding(key)}
                    disabled={!canEdit}
                    aria-label={`Добавить блюдо на ${dayLabel(d)}`}
                  >
                    <Plus />
                  </Button>
                </header>

                {list.length === 0 ? (
                  <button
                    className="mt-3 flex flex-1 items-center justify-center rounded-2xl border-2 border-dashed border-input/70 py-5 text-sm text-muted-foreground transition-colors hover:border-primary hover:text-foreground disabled:pointer-events-none"
                    onClick={() => setAdding(key)}
                    disabled={!canEdit}
                  >
                    <Plus className="mr-1 size-4" /> Добавить блюдо
                  </button>
                ) : (
                  <div className="mt-3 grid gap-3">
                    {SLOTS.filter((s) => list.some((e) => e.slot === s.id)).map((s) => (
                      <div key={s.id}>
                        <p className="mb-1 text-[11px] font-semibold tracking-wide text-muted-foreground uppercase">{s.label}</p>
                        <ul className="grid gap-1.5">
                          {list
                            .filter((e) => e.slot === s.id)
                            .map((e) => (
                              <li key={e.id}>
                                <div className="flex items-center gap-3 rounded-2xl bg-muted/50 p-2">
                                  {e.recipe ? (
                                    <Link to={`/recipes/${e.recipe.id}`} className="flex min-w-0 flex-1 items-center gap-3">
                                      <div className="size-12 shrink-0 overflow-hidden rounded-xl bg-accent">
                                        {e.recipe.thumb_url ? (
                                          <img src={e.recipe.thumb_url} alt="" loading="lazy" className="h-full w-full object-cover" />
                                        ) : (
                                          <UtensilsCrossed className="m-3.5 size-5 text-primary/40" />
                                        )}
                                      </div>
                                      <span className="min-w-0">
                                        <span className="line-clamp-2 text-sm leading-snug font-medium">{e.recipe.title}</span>
                                        <span className="block text-xs text-muted-foreground">
                                          {e.servings} {plural(e.servings, "порция", "порции", "порций")}
                                          {e.recipe.total_minutes ? ` · ${formatMinutes(e.recipe.total_minutes)}` : ""}
                                        </span>
                                      </span>
                                    </Link>
                                  ) : (
                                    <span className="flex min-w-0 flex-1 items-center gap-3">
                                      <span className="flex size-12 shrink-0 items-center justify-center rounded-xl bg-card">
                                        <StickyNote className="size-5 text-muted-foreground" />
                                      </span>
                                      <span className="text-sm font-medium">{e.note}</span>
                                    </span>
                                  )}
                                  <Button
                                    variant="ghost"
                                    size="sm"
                                    className="shrink-0 px-2.5 text-muted-foreground"
                                    onClick={() => setEditing(e)}
                                    disabled={!canEdit}
                                    aria-label="Изменить"
                                  >
                                    Изменить
                                  </Button>
                                </div>
                              </li>
                            ))}
                        </ul>
                      </div>
                    ))}
                  </div>
                )}
              </section>
            );
          })}
        </div>
      )}

      {!entries.length && !plan.isLoading && (
        <p className="flex items-center justify-center gap-2 text-center text-sm text-muted-foreground">
          <CalendarDays className="size-4" /> Блюдо можно добавить и со страницы рецепта — кнопка «В меню».
        </p>
      )}

      {adding && <AddEntrySheet day={adding} ownerId={ownerParam} onClose={() => setAdding(null)} />}
      {editing && <EntrySheet entry={editing} days={days} onClose={() => setEditing(null)} />}
      {shopping && (
        <ToShoppingSheet start={start} end={end} ownerId={ownerParam} count={withRecipe.length} onClose={() => setShopping(false)} />
      )}
      {sharing && plan.data && <MembersSheet members={plan.data.members} onClose={() => setSharing(false)} />}
    </div>
  );
}
