import { useEffect, useRef, useState, type ChangeEvent, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Camera, Check, Download, Globe, KeyRound, Loader2, Pencil, Plus, Settings, Shield, Tags, Trash2, Upload, UserPlus, Users, X, type LucideIcon } from "lucide-react";
import { useSearchParams } from "react-router";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Field } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { api, updateCurrentUser, type PublicSettings, type User } from "@/lib/api";
import { Avatar } from "@/components/Avatar";
import { AvatarCropper } from "@/components/AvatarCropper";
import { useAuth } from "@/lib/auth";
import { useSettings } from "@/lib/useSettings";
import { cn } from "@/lib/utils";
import { RecipeImportsCard } from "@/components/RecipeImportsCard";

function SettingsCard() {
  const queryClient = useQueryClient();
  const { data: settings } = useSettings();
  const [siteName, setSiteName] = useState("");

  useEffect(() => {
    if (settings) setSiteName(settings.site_name);
  }, [settings]);

  const mutation = useMutation({
    mutationFn: (data: Partial<PublicSettings>) => api.settings.update(data),
    onSuccess: (data) => {
      queryClient.setQueryData(["settings"], data);
      toast.success("Сохранено");
    },
    onError: (err) => toast.error(err.message),
  });

  return (
    <Card>
      <CardHeader>
        <CardTitle>Сервис</CardTitle>
        <CardDescription>Название и доступ для новых пользователей.</CardDescription>
      </CardHeader>
      <CardContent className="grid gap-6">
        <form
          className="flex flex-col gap-3 sm:flex-row sm:items-end"
          onSubmit={(e) => {
            e.preventDefault();
            mutation.mutate({ site_name: siteName });
          }}
        >
          <div className="flex-1">
            <Field id="site_name" label="Название">
              <Input id="site_name" value={siteName} onChange={(e) => setSiteName(e.target.value)} />
            </Field>
          </div>
          <Button type="submit" variant="secondary" disabled={mutation.isPending || siteName === settings?.site_name}>
            Сохранить
          </Button>
        </form>

        <label className="flex cursor-pointer items-start justify-between gap-4 rounded-xl bg-muted/60 p-4">
          <span>
            <span className="block font-semibold">Свободная регистрация</span>
            <span className="text-sm text-muted-foreground">
              {settings?.registration_mode === "open"
                ? "Сейчас любой может создать аккаунт."
                : "Сейчас регистрация закрыта — новых пользователей не будет."}
            </span>
          </span>
          <Switch
            checked={settings?.registration_mode === "open"}
            disabled={mutation.isPending}
            onCheckedChange={(v) => mutation.mutate({ registration_mode: v ? "open" : "closed" })}
          />
        </label>
      </CardContent>
    </Card>
  );
}

function CategoriesCard() {
  const queryClient = useQueryClient();
  const categories = useQuery({ queryKey: ["categories"], queryFn: api.catalog.categories });
  const [newName, setNewName] = useState("");
  const [editing, setEditing] = useState<{ id: number; name: string } | null>(null);

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ["categories"] });
    queryClient.invalidateQueries({ queryKey: ["recipes"] });
  };
  const create = useMutation({
    mutationFn: (name: string) => api.catalog.createCategory(name),
    onSuccess: () => {
      setNewName("");
      refresh();
    },
    onError: (e) => toast.error(e.message),
  });
  const update = useMutation({
    mutationFn: (c: { id: number; name: string; sort_order: number }) =>
      api.catalog.updateCategory(c.id, { name: c.name, sort_order: c.sort_order }),
    onSuccess: () => {
      setEditing(null);
      refresh();
    },
    onError: (e) => toast.error(e.message),
  });
  const remove = useMutation({
    mutationFn: (id: number) => api.catalog.deleteCategory(id),
    onSuccess: refresh,
    onError: (e) => toast.error(e.message),
  });

  const list = categories.data ?? [];
  const swap = (i: number, j: number) => {
    const a = list[i];
    const b = list[j];
    if (!a || !b) return;
    // Пересчитываем порядок всем, чтобы не было одинаковых sort_order
    list.forEach((c, idx) => {
      const order = idx === i ? j : idx === j ? i : idx;
      if (order !== c.sort_order) update.mutate({ id: c.id, name: c.name, sort_order: order });
    });
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>Категории</CardTitle>
        <CardDescription>Порядок здесь — порядок фильтров на главной. При удалении рецепты остаются без категории.</CardDescription>
      </CardHeader>
      <CardContent className="grid gap-4">
        <form
          className="flex gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            if (newName.trim()) create.mutate(newName.trim());
          }}
        >
          <Input placeholder="Новая категория" value={newName} onChange={(e) => setNewName(e.target.value)} />
          <Button type="submit" variant="secondary" disabled={!newName.trim() || create.isPending}>
            <Plus /> Добавить
          </Button>
        </form>
        {list.length === 0 ? (
          <p className="text-sm text-muted-foreground">Категорий пока нет.</p>
        ) : (
          <ul className="divide-y rounded-xl border">
            {list.map((c, i) => (
              <li key={c.id} className="flex items-center gap-2 px-3 py-2">
                {editing?.id === c.id ? (
                  <form
                    className="flex flex-1 items-center gap-2"
                    onSubmit={(e) => {
                      e.preventDefault();
                      if (editing.name.trim()) update.mutate({ id: c.id, name: editing.name.trim(), sort_order: c.sort_order });
                    }}
                  >
                    <Input
                      autoFocus
                      className="h-9"
                      value={editing.name}
                      onChange={(e) => setEditing({ id: c.id, name: e.target.value })}
                    />
                    <Button type="submit" size="icon" variant="ghost" aria-label="Сохранить">
                      <Check />
                    </Button>
                    <Button type="button" size="icon" variant="ghost" aria-label="Отмена" onClick={() => setEditing(null)}>
                      <X />
                    </Button>
                  </form>
                ) : (
                  <>
                    <span className="flex-1 font-semibold">{c.name}</span>
                    <span className="text-xs text-muted-foreground">{c.recipe_count}</span>
                    <Button size="icon" variant="ghost" aria-label="Выше" disabled={i === 0} onClick={() => swap(i, i - 1)}>
                      <span className="text-base leading-none">↑</span>
                    </Button>
                    <Button size="icon" variant="ghost" aria-label="Переименовать" onClick={() => setEditing({ id: c.id, name: c.name })}>
                      <Pencil />
                    </Button>
                    <Button
                      size="icon"
                      variant="ghost"
                      aria-label="Удалить"
                      className="hover:text-destructive"
                      onClick={() => {
                        if (confirm(`Удалить категорию «${c.name}»?`)) remove.mutate(c.id);
                      }}
                    >
                      <Trash2 />
                    </Button>
                  </>
                )}
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

function BackupCard() {
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const input = useRef<HTMLInputElement>(null);
  const [downloading, setDownloading] = useState(false);
  const restore = useMutation({
    mutationFn: (file: File) => api.backup.restore(file),
    onSuccess: (r) => {
      queryClient.invalidateQueries();
      const parts = [`добавлено ${r.created}`];
      if (r.skipped) parts.push(`пропущено повторов ${r.skipped}`);
      if (r.failed) parts.push(`с ошибкой ${r.failed}`);
      (r.failed ? toast.warning : toast.success)(`Восстановление: ${parts.join(", ")}`, {
        description: r.errors.slice(0, 3).join("\n") || undefined,
        duration: 10000,
      });
    },
    onError: (e) => toast.error(e.message),
  });

  return (
    <Card>
      <CardHeader>
        <CardTitle>Резервная копия</CardTitle>
        <CardDescription>
          {user?.is_admin ? "Все рецепты" : "Ваши рецепты"} с фото в одном zip-архиве. Из него же можно восстановить
          рецепты или перенести их на другой сервер. Повторы (то же название у того же автора) пропускаются.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-wrap gap-3">
        <Button
          variant="secondary"
          disabled={downloading}
          onClick={async () => {
            setDownloading(true);
            try {
              await api.backup.download();
            } catch (e) {
              toast.error((e as Error).message);
            } finally {
              setDownloading(false);
            }
          }}
        >
          {downloading ? <Loader2 className="animate-spin" /> : <Download />} Скачать архив
        </Button>
        <Button variant="outline" disabled={restore.isPending} onClick={() => input.current?.click()}>
          {restore.isPending ? <Loader2 className="animate-spin" /> : <Upload />} Восстановить из архива
        </Button>
        <input
          ref={input}
          type="file"
          accept=".zip,application/zip"
          hidden
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) restore.mutate(file);
            e.target.value = "";
          }}
        />
      </CardContent>
    </Card>
  );
}

function AddUserForm({ onDone }: { onDone: () => void }) {
  const queryClient = useQueryClient();
  const [form, setForm] = useState({ username: "", display_name: "", email: "", password: "", is_admin: false });
  const create = useMutation({
    mutationFn: () => api.admin.createUser(form),
    onSuccess: (user) => {
      queryClient.setQueryData<User[]>(["admin-users"], (list) => (list ? [...list, user] : [user]));
      toast.success(`Пользователь ${user.username} добавлен`, {
        description: "Передайте ему логин и пароль — сменить пароль можно здесь же.",
      });
      onDone();
    },
    onError: (e) => toast.error(e.message),
  });
  const set = (k: "username" | "display_name" | "email" | "password") => (e: ChangeEvent<HTMLInputElement>) =>
    setForm((f) => ({ ...f, [k]: e.target.value }));

  return (
    <form
      className="grid gap-4 border-b bg-muted/40 px-6 py-5"
      onSubmit={(e) => {
        e.preventDefault();
        create.mutate();
      }}
    >
      <div className="grid gap-4 sm:grid-cols-2">
        <Field id="nu-username" label="Логин" hint="Латиница, цифры, _ . -">
          <Input id="nu-username" required autoComplete="off" value={form.username} onChange={set("username")} />
        </Field>
        <Field id="nu-name" label="Имя">
          <Input id="nu-name" autoComplete="off" value={form.display_name} onChange={set("display_name")} />
        </Field>
        <Field id="nu-email" label="Email">
          <Input id="nu-email" type="email" required autoComplete="off" value={form.email} onChange={set("email")} />
        </Field>
        <Field id="nu-password" label="Пароль" hint="Минимум 8 символов">
          <Input
            id="nu-password"
            type="text"
            required
            minLength={8}
            autoComplete="new-password"
            value={form.password}
            onChange={set("password")}
          />
        </Field>
      </div>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <label className="flex items-center gap-2 text-sm font-semibold">
          <Switch checked={form.is_admin} onCheckedChange={(v) => setForm((f) => ({ ...f, is_admin: v }))} />
          Администратор
        </label>
        <div className="flex gap-2">
          <Button type="button" variant="ghost" onClick={onDone}>
            Отмена
          </Button>
          <Button type="submit" disabled={create.isPending}>
            {create.isPending && <Loader2 className="animate-spin" />} Добавить
          </Button>
        </div>
      </div>
    </form>
  );
}

function EditUserDialog({ user, onClose }: { user: User; onClose: () => void }) {
  const { user: me } = useAuth();
  const queryClient = useQueryClient();
  const input = useRef<HTMLInputElement>(null);
  const [current, setCurrent] = useState(user);
  const [form, setForm] = useState({ username: user.username, display_name: user.display_name, email: user.email });
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);

  const apply = (u: User) => {
    setCurrent(u);
    queryClient.setQueryData<User[]>(["admin-users"], (list) => list?.map((x) => (x.id === u.id ? u : x)));
    queryClient.invalidateQueries({ queryKey: ["recipes"] });
    if (u.id === me?.id) updateCurrentUser(u);
  };

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && !file && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose, file]);

  const changed =
    form.username.trim() !== current.username ||
    form.display_name.trim() !== current.display_name ||
    form.email.trim().toLowerCase() !== current.email;

  const save = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    try {
      apply(
        await api.admin.updateUser(user.id, {
          username: form.username.trim(),
          display_name: form.display_name.trim(),
          email: form.email.trim(),
        }),
      );
      toast.success("Профиль сохранён");
      onClose();
    } catch (err) {
      toast.error((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const name = current.display_name || current.username;

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/45 backdrop-blur-sm sm:items-center sm:p-4" role="dialog" aria-modal onClick={onClose}>
      <div
        className="max-h-[92svh] w-full max-w-md overflow-y-auto rounded-t-3xl border bg-card p-6 pb-[max(1.5rem,env(safe-area-inset-bottom))] shadow-xl sm:rounded-3xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-semibold">Профиль пользователя</h2>
          <Button variant="ghost" size="icon" onClick={onClose} aria-label="Закрыть">
            <X />
          </Button>
        </div>

        <div className="mt-4 flex items-center gap-4">
          <button
            type="button"
            onClick={() => input.current?.click()}
            className="group relative shrink-0 rounded-full outline-none focus-visible:ring-4 focus-visible:ring-ring"
            aria-label="Загрузить фото"
          >
            <Avatar src={current.avatar_url} name={name} className="size-20 text-2xl" />
            <span className="absolute inset-0 flex items-center justify-center rounded-full bg-black/45 text-white opacity-0 transition-opacity group-hover:opacity-100">
              <Camera className="size-5" />
            </span>
          </button>
          <div className="flex flex-wrap gap-2">
            <Button size="sm" variant="secondary" onClick={() => input.current?.click()}>
              <Camera /> {current.avatar_url ? "Сменить фото" : "Загрузить фото"}
            </Button>
            {current.avatar_url && (
              <Button
                size="sm"
                variant="ghost"
                onClick={async () => {
                  try {
                    apply(await api.admin.removeAvatar(user.id));
                  } catch (err) {
                    toast.error((err as Error).message);
                  }
                }}
              >
                <Trash2 /> Убрать
              </Button>
            )}
          </div>
          <input
            ref={input}
            type="file"
            accept="image/*"
            hidden
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) setFile(f);
              e.target.value = "";
            }}
          />
        </div>

        <form onSubmit={save} className="mt-6 grid gap-4">
          <Field id="eu-name" label="Имя">
            <Input id="eu-name" value={form.display_name} onChange={(e) => setForm((f) => ({ ...f, display_name: e.target.value }))} />
          </Field>
          <Field id="eu-login" label="Логин" hint="Латиница, цифры, _ . -">
            <Input
              id="eu-login"
              required
              autoComplete="off"
              value={form.username}
              onChange={(e) => setForm((f) => ({ ...f, username: e.target.value }))}
            />
          </Field>
          <Field id="eu-email" label="Email">
            <Input
              id="eu-email"
              type="email"
              required
              autoComplete="off"
              value={form.email}
              onChange={(e) => setForm((f) => ({ ...f, email: e.target.value }))}
            />
          </Field>
          <div className="mt-2 flex justify-end gap-2">
            <Button type="button" variant="ghost" onClick={onClose}>
              Отмена
            </Button>
            <Button type="submit" disabled={busy || !changed}>
              {busy && <Loader2 className="animate-spin" />} Сохранить
            </Button>
          </div>
        </form>
      </div>

      {file && (
        // клики внутри окна кадрирования не должны закрывать окно профиля под ним
        <div onClick={(e) => e.stopPropagation()}>
        <AvatarCropper
          file={file}
          onCancel={() => setFile(null)}
          onDone={async (blob) => {
            try {
              apply(await api.admin.setAvatar(user.id, blob));
              toast.success("Фото обновлено");
              setFile(null);
            } catch (err) {
              toast.error((err as Error).message);
            }
          }}
        />
        </div>
      )}
    </div>
  );
}

function ResetPassword({ user, onDone }: { user: User; onDone: () => void }) {
  const [password, setPassword] = useState("");
  const reset = useMutation({
    mutationFn: () => api.admin.resetPassword(user.id, password),
    onSuccess: () => {
      toast.success(`Пароль для ${user.username} изменён`, { description: "Пользователь вышел со всех устройств." });
      onDone();
    },
    onError: (e) => toast.error(e.message),
  });
  return (
    <form
      className="flex w-full flex-wrap items-center gap-2 pl-14"
      onSubmit={(e) => {
        e.preventDefault();
        reset.mutate();
      }}
    >
      <Input
        autoFocus
        type="text"
        minLength={8}
        required
        placeholder="Новый пароль, от 8 символов"
        className="h-9 max-w-xs flex-1"
        autoComplete="new-password"
        value={password}
        onChange={(e) => setPassword(e.target.value)}
      />
      <Button type="submit" size="sm" disabled={reset.isPending}>
        Сохранить
      </Button>
      <Button type="button" size="sm" variant="ghost" onClick={onDone}>
        Отмена
      </Button>
    </form>
  );
}

function UsersCard() {
  const { user: me } = useAuth();
  const queryClient = useQueryClient();
  const users = useQuery({ queryKey: ["admin-users"], queryFn: api.admin.users });
  const [adding, setAdding] = useState(false);
  const [resetFor, setResetFor] = useState<number | null>(null);
  const [editing, setEditing] = useState<User | null>(null);

  const mutation = useMutation({
    mutationFn: ({ id, data }: { id: number; data: { is_admin?: boolean; is_active?: boolean } }) =>
      api.admin.updateUser(id, data),
    onSuccess: (updated) =>
      queryClient.setQueryData<User[]>(["admin-users"], (list) => list?.map((u) => (u.id === updated.id ? updated : u))),
    onError: (err) => toast.error(err.message),
  });

  return (
    <Card>
      <CardHeader>
        <div className="flex items-start justify-between gap-3">
          <div className="grid gap-1.5">
            <CardTitle>Пользователи</CardTitle>
            <CardDescription>Добавление работает и при закрытой регистрации.</CardDescription>
          </div>
          {!adding && (
            <Button size="sm" variant="secondary" onClick={() => setAdding(true)}>
              <UserPlus /> Добавить
            </Button>
          )}
        </div>
      </CardHeader>
      <CardContent className="p-0 pt-4">
        {adding && <AddUserForm onDone={() => setAdding(false)} />}
        {users.isLoading ? (
          <div className="flex justify-center p-8">
            <Loader2 className="size-5 animate-spin text-muted-foreground" />
          </div>
        ) : (
          <ul className="divide-y">
            {users.data?.map((u) => (
              <li key={u.id} className={cn("flex flex-wrap items-center gap-4 px-6 py-4", !u.is_active && "opacity-55")}>
                <span className="relative">
                  <Avatar src={u.avatar_url} name={u.display_name || u.username} className="size-10" />
                  {u.is_admin && (
                    <span className="absolute -right-0.5 -bottom-0.5 flex size-4.5 items-center justify-center rounded-full bg-primary text-primary-foreground ring-2 ring-card" title="Администратор">
                      <Shield className="size-2.5" />
                    </span>
                  )}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate font-semibold">
                    {u.display_name || u.username}
                    {u.id === me?.id && <span className="ml-2 text-xs font-medium text-muted-foreground">это вы</span>}
                  </span>
                  <span className="block truncate text-sm text-muted-foreground">
                    @{u.username} · {u.email}
                  </span>
                </span>
                <Button size="icon" variant="ghost" aria-label="Изменить профиль" title="Изменить профиль" onClick={() => setEditing(u)}>
                  <Pencil />
                </Button>
                <Button
                  size="icon"
                  variant="ghost"
                  aria-label="Сменить пароль"
                  title="Сменить пароль"
                  onClick={() => setResetFor(resetFor === u.id ? null : u.id)}
                >
                  <KeyRound />
                </Button>
                <label className="flex items-center gap-2 text-sm">
                  Админ
                  <Switch
                    checked={u.is_admin}
                    disabled={u.id === me?.id || mutation.isPending}
                    onCheckedChange={(v) => mutation.mutate({ id: u.id, data: { is_admin: v } })}
                  />
                </label>
                <label className="flex items-center gap-2 text-sm">
                  Активен
                  <Switch
                    checked={u.is_active}
                    disabled={u.id === me?.id || mutation.isPending}
                    onCheckedChange={(v) => mutation.mutate({ id: u.id, data: { is_active: v } })}
                  />
                </label>
                {resetFor === u.id && <ResetPassword user={u} onDone={() => setResetFor(null)} />}
              </li>
            ))}
          </ul>
        )}
        {editing && <EditUserDialog user={editing} onClose={() => setEditing(null)} />}
      </CardContent>
    </Card>
  );
}

type AdminSection = "sources" | "service" | "users" | "categories";

const sections: { id: AdminSection; label: string; hint: string; icon: LucideIcon }[] = [
  { id: "sources", label: "Источники", hint: "Сайты и база рецептов", icon: Globe },
  { id: "service", label: "Сервис", hint: "Название и резервная копия", icon: Settings },
  { id: "users", label: "Пользователи", hint: "Учётные записи и роли", icon: Users },
  { id: "categories", label: "Категории", hint: "Справочник категорий", icon: Tags },
];

function isSection(value: string | null): value is AdminSection {
  return sections.some((section) => section.id === value);
}

export default function AdminPage() {
  const [params, setParams] = useSearchParams();
  const requested = params.get("section");
  const active: AdminSection = isSection(requested) ? requested : "sources";

  function choose(section: AdminSection) {
    const next = new URLSearchParams(params);
    next.set("section", section);
    setParams(next, { replace: true });
  }

  return (
    <div className="grid gap-8">
      <h1 className="title-display text-4xl sm:text-5xl">Управление</h1>
      <div className="grid items-start gap-6 lg:grid-cols-[15rem_minmax(0,1fr)]">
        <nav aria-label="Разделы управления" className="lg:sticky lg:top-24">
          <Card className="p-2">
            <ul className="flex gap-1 overflow-x-auto lg:flex-col">
              {sections.map(({ id, label, hint, icon: Icon }) => (
                <li key={id} className="shrink-0">
                  <button
                    type="button"
                    aria-current={active === id ? "page" : undefined}
                    onClick={() => choose(id)}
                    className={cn(
                      "flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-left text-sm transition-colors",
                      active === id ? "bg-primary/10 font-semibold text-primary" : "text-muted-foreground hover:bg-muted hover:text-foreground",
                    )}
                  >
                    <Icon className="size-4 shrink-0" />
                    <span className="grid">
                      <span>{label}</span>
                      <span className="hidden text-xs font-normal text-muted-foreground lg:block">{hint}</span>
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          </Card>
        </nav>
        <section className="grid min-w-0 content-start gap-6">
          {active === "sources" && <RecipeImportsCard />}
          {active === "service" && <><SettingsCard /><BackupCard /></>}
          {active === "users" && <UsersCard />}
          {active === "categories" && <CategoriesCard />}
        </section>
      </div>
    </div>
  );
}
