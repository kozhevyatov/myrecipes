import { useState, type FormEvent } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { CalendarCheck, Loader2, X } from "lucide-react";
import { toast } from "sonner";
import { Avatar } from "@/components/Avatar";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { api, type Recipe } from "@/lib/api";
import { plural } from "@/lib/format";

function today() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function formatDate(iso: string) {
  const [y, m, d] = iso.split("-").map(Number);
  const date = new Date(y, m - 1, d);
  const sameYear = y === new Date().getFullYear();
  return date.toLocaleDateString("ru-RU", { day: "numeric", month: "long", ...(sameYear ? {} : { year: "numeric" }) });
}

/** «Я приготовил(а)»: дата, заметка (что поменял, как получилось) и история. */
export function CookLog({ recipe }: { recipe: Recipe }) {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [date, setDate] = useState(today);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const log = recipe.cook_log;

  const save = (r: Recipe) => {
    queryClient.setQueryData(["recipe", recipe.id], r);
    queryClient.invalidateQueries({ queryKey: ["recipes"] });
  };

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    try {
      save(await api.recipes.markCooked(recipe.id, { cooked_on: date, note }));
      setOpen(false);
      setNote("");
      setDate(today());
      toast.success("Отмечено");
    } catch (err) {
      toast.error((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="grid gap-4 print:hidden">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-xl font-semibold">История</h2>
          <p className="text-sm text-muted-foreground">
            {log.length
              ? `Готовили ${log.length} ${plural(log.length, "раз", "раза", "раз")}, последний — ${formatDate(log[0].cooked_on)}`
              : "Ещё не готовили"}
          </p>
        </div>
        {!open && (
          <Button variant="outline" onClick={() => setOpen(true)}>
            <CalendarCheck /> Я приготовил(а)
          </Button>
        )}
      </div>

      {open && (
        <form onSubmit={submit} className="grid gap-3 rounded-2xl border bg-card p-4 sm:p-5">
          <div className="flex flex-wrap items-center gap-3">
            <label className="text-sm text-muted-foreground" htmlFor="cooked-on">
              Когда
            </label>
            <Input
              id="cooked-on"
              type="date"
              className="h-10 w-auto"
              max={today()}
              value={date}
              onChange={(e) => setDate(e.target.value)}
              required
            />
          </div>
          <Textarea
            rows={2}
            placeholder="Заметка: что поменяли, как получилось — необязательно"
            value={note}
            onChange={(e) => setNote(e.target.value)}
          />
          <div className="flex justify-end gap-2">
            <Button type="button" variant="ghost" onClick={() => setOpen(false)}>
              Отмена
            </Button>
            <Button type="submit" disabled={busy}>
              {busy && <Loader2 className="animate-spin" />} Отметить
            </Button>
          </div>
        </form>
      )}

      {log.length > 0 && (
        <ul className="grid gap-2">
          {log.map((entry) => (
            <li key={entry.id} className="flex gap-3 rounded-2xl border bg-card px-4 py-3">
              <Avatar src={entry.author.avatar_url} name={entry.author.name} className="size-8 text-xs" />
              <div className="min-w-0 flex-1">
                <p className="text-sm">
                  <span className="font-semibold">{entry.author.name}</span>
                  <span className="text-muted-foreground"> · {formatDate(entry.cooked_on)}</span>
                </p>
                {entry.note && <p className="mt-0.5 text-sm whitespace-pre-line">{entry.note}</p>}
              </div>
              {entry.can_delete && (
                <button
                  className="self-start rounded-md p-1 text-muted-foreground hover:text-destructive"
                  aria-label="Удалить запись"
                  onClick={async () => {
                    try {
                      save(await api.recipes.deleteCooked(recipe.id, entry.id));
                    } catch (err) {
                      toast.error((err as Error).message);
                    }
                  }}
                >
                  <X className="size-4" />
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
