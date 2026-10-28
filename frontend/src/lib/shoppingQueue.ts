/**
 * Изменения списков покупок, которые ещё не дошли до сервера.
 *
 * Любое действие (отметить, добавить, удалить, очистить) сначала попадает в очередь
 * и сразу отображается на экране, затем очередь отправляется на сервер. Нет связи —
 * действия ждут и уходят, как только сеть появится. Так список работает в магазине,
 * где интернет то есть, то нет.
 */
import { useEffect, useState } from "react";
import { ApiError, api, type ShoppingItem } from "./api";

type Op =
  | { key: string; kind: "check"; listId: number; itemId: number; checked: boolean }
  | { key: string; kind: "remove"; listId: number; itemId: number }
  | { key: string; kind: "add"; listId: number; tempId: number; text: string; checked?: boolean }
  | { key: string; kind: "clear"; listId: number; checkedOnly: boolean };

type NewOp = Op extends infer T ? (T extends Op ? Omit<T, "key"> : never) : never;

const STORE = "shopping-queue";
const EVENT = "shopping-queue";

function load(): Op[] {
  try {
    return JSON.parse(localStorage.getItem(STORE) || "[]");
  } catch {
    return [];
  }
}

function save(ops: Op[]) {
  try {
    localStorage.setItem(STORE, JSON.stringify(ops));
  } catch {
    /* ignore */
  }
  window.dispatchEvent(new Event(EVENT));
}

let seq = 0;
const newKey = () => `${Date.now()}-${++seq}`;

/** Временный id для пункта, добавленного без связи (отрицательный — не пересекается с серверными). */
export function tempId() {
  return -Date.now() - ++seq;
}

export function enqueue(op: NewOp) {
  const ops = load();
  // Действия над ещё не отправленным пунктом меняют саму операцию добавления
  if ((op.kind === "check" || op.kind === "remove") && op.itemId < 0) {
    const add = ops.find((o) => o.kind === "add" && o.tempId === op.itemId) as Extract<Op, { kind: "add" }> | undefined;
    if (add) {
      if (op.kind === "remove") save(ops.filter((o) => o !== add));
      else {
        add.checked = op.checked;
        save(ops);
      }
      return;
    }
  }
  ops.push({ ...op, key: newKey() } as Op);
  save(ops);
  void flush();
}

/** Наложить неотправленные изменения на данные с сервера (или из сохранённой копии). */
export function overlay(listId: number, items: ShoppingItem[]): (ShoppingItem & { pending?: boolean })[] {
  let result: (ShoppingItem & { pending?: boolean })[] = items.map((i) => ({ ...i }));
  for (const op of load()) {
    if (op.listId !== listId) continue;
    if (op.kind === "check") {
      result = result.map((i) => (i.id === op.itemId ? { ...i, checked: op.checked, pending: true } : i));
    } else if (op.kind === "remove") {
      result = result.filter((i) => i.id !== op.itemId);
    } else if (op.kind === "add") {
      result.push({ id: op.tempId, name: op.text, amount: null, unit: "", note: "", checked: !!op.checked, pending: true });
    } else if (op.kind === "clear") {
      result = op.checkedOnly ? result.filter((i) => !i.checked) : [];
    }
  }
  // некупленное сверху
  return [...result.filter((i) => !i.checked), ...result.filter((i) => i.checked)];
}

export function pendingCount(listId?: number) {
  return load().filter((o) => listId === undefined || o.listId === listId).length;
}

let flushing: Promise<void> | null = null;
const listeners = new Set<() => void>();

/** Вызывается после успешной отправки — чтобы перечитать списки. */
export function onFlushed(fn: () => void) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

async function send(op: Op) {
  switch (op.kind) {
    case "check":
      return api.shopping.update(op.itemId, { checked: op.checked });
    case "remove":
      return api.shopping.remove(op.itemId);
    case "clear":
      return api.shopping.clear(op.listId, op.checkedOnly);
    case "add": {
      // Отметили ещё до отправки: найдём новый пункт по разнице id «до» и «после»
      const before = op.checked ? new Set((await api.shopping.items(op.listId)).map((i) => i.id)) : null;
      const items = await api.shopping.addText(op.listId, op.text);
      if (before) {
        const created = items.find((i) => !before.has(i.id));
        if (created) await api.shopping.update(created.id, { checked: true });
      }
      return items;
    }
  }
}

/** Отправить очередь по порядку. Нет сети — остановиться и попробовать позже. */
export function flush(): Promise<void> {
  if (flushing) return flushing;
  flushing = (async () => {
    let sent = 0;
    while (true) {
      const ops = load();
      const op = ops[0];
      if (!op) break;
      try {
        await send(op);
      } catch (err) {
        // Нет сети или сессия истекла — ждём; иная ошибка сервера (пункт уже удалили, нет доступа) — выбрасываем
        if (!(err instanceof ApiError) || err.status === 401) break;
      }
      save(load().filter((o) => o.key !== op.key));
      sent++;
    }
    if (sent) listeners.forEach((fn) => fn());
  })().finally(() => {
    flushing = null;
  });
  return flushing;
}

/** Перерисовка при изменении очереди. */
export function useQueueVersion() {
  const [v, setV] = useState(0);
  useEffect(() => {
    const bump = () => setV((x) => x + 1);
    window.addEventListener(EVENT, bump);
    return () => window.removeEventListener(EVENT, bump);
  }, []);
  return v;
}

/** Очистка при выходе из аккаунта. */
export function clearQueue() {
  try {
    localStorage.removeItem(STORE);
  } catch {
    /* ignore */
  }
}
