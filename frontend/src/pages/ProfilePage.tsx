import { useEffect, useRef, useState, type FormEvent } from "react";
import { Camera, Loader2, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { Avatar } from "@/components/Avatar";
import { AvatarCropper } from "@/components/AvatarCropper";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Field } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { api, setSession, updateCurrentUser } from "@/lib/api";
import { useAuth } from "@/lib/auth";

function AvatarCard() {
  const { user } = useAuth();
  const input = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  if (!user) return null;
  const name = user.display_name || user.username;

  return (
    <Card>
      <CardContent className="flex flex-col items-center gap-4 text-center sm:flex-row sm:text-left">
        <button
          type="button"
          onClick={() => input.current?.click()}
          className="group relative shrink-0 rounded-full outline-none focus-visible:ring-4 focus-visible:ring-ring"
          aria-label="Загрузить фото"
        >
          <Avatar src={user.avatar_url} name={name} className="size-24 text-3xl" />
          <span className="absolute inset-0 flex items-center justify-center rounded-full bg-black/45 text-white opacity-0 transition-opacity group-hover:opacity-100">
            <Camera className="size-6" />
          </span>
        </button>
        <div className="grid flex-1 gap-1">
          <p className="text-xl font-semibold">{name}</p>
          <p className="text-sm text-muted-foreground">
            @{user.username}
            {user.is_admin && " · администратор"}
          </p>
          <div className="mt-2 flex flex-wrap justify-center gap-2 sm:justify-start">
            <Button size="sm" variant="secondary" onClick={() => input.current?.click()}>
              <Camera /> {user.avatar_url ? "Сменить фото" : "Загрузить фото"}
            </Button>
            {user.avatar_url && (
              <Button
                size="sm"
                variant="ghost"
                disabled={busy}
                onClick={async () => {
                  setBusy(true);
                  try {
                    updateCurrentUser(await api.me.removeAvatar());
                  } catch (e) {
                    toast.error((e as Error).message);
                  } finally {
                    setBusy(false);
                  }
                }}
              >
                <Trash2 /> Убрать
              </Button>
            )}
          </div>
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
      </CardContent>
      {file && (
        <AvatarCropper
          file={file}
          onCancel={() => setFile(null)}
          onDone={async (blob) => {
            try {
              updateCurrentUser(await api.me.uploadAvatar(blob));
              toast.success("Фото профиля обновлено");
              setFile(null);
            } catch (e) {
              toast.error((e as Error).message);
            }
          }}
        />
      )}
    </Card>
  );
}

function DetailsCard() {
  const { user } = useAuth();
  const [displayName, setDisplayName] = useState("");
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (user) {
      setDisplayName(user.display_name);
      setEmail(user.email);
    }
  }, [user]);

  if (!user) return null;
  const changed = displayName.trim() !== user.display_name || email.trim().toLowerCase() !== user.email;

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    try {
      updateCurrentUser(await api.me.update({ display_name: displayName.trim(), email: email.trim() }));
      toast.success("Данные сохранены");
    } catch (err) {
      toast.error((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>Личные данные</CardTitle>
        <CardDescription>Имя видно другим пользователям у ваших рецептов. Логин изменить нельзя.</CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={submit} className="grid gap-5">
          <Field id="p-name" label="Имя">
            <Input id="p-name" autoComplete="name" value={displayName} onChange={(e) => setDisplayName(e.target.value)} />
          </Field>
          <Field id="p-email" label="Email">
            <Input id="p-email" type="email" required autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} />
          </Field>
          <div>
            <Button type="submit" disabled={busy || !changed}>
              {busy && <Loader2 className="animate-spin" />} Сохранить
            </Button>
          </div>
        </form>
      </CardContent>
    </Card>
  );
}

function PasswordCard() {
  const [form, setForm] = useState({ current: "", next: "", confirm: "" });
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (form.next !== form.confirm) return toast.error("Новые пароли не совпадают");
    setBusy(true);
    try {
      setSession(await api.me.changePassword(form.current, form.next));
      setForm({ current: "", next: "", confirm: "" });
      toast.success("Пароль изменён", { description: "На остальных устройствах нужно будет войти заново." });
    } catch (err) {
      toast.error((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>Пароль</CardTitle>
        <CardDescription>После смены пароля остальные устройства выйдут из аккаунта, а это останется в системе.</CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={submit} className="grid gap-5">
          <Field id="pw-current" label="Текущий пароль">
            <Input
              id="pw-current"
              type="password"
              required
              autoComplete="current-password"
              value={form.current}
              onChange={(e) => setForm((f) => ({ ...f, current: e.target.value }))}
            />
          </Field>
          <div className="grid gap-5 sm:grid-cols-2">
            <Field id="pw-new" label="Новый пароль" hint="Минимум 8 символов">
              <Input
                id="pw-new"
                type="password"
                required
                minLength={8}
                autoComplete="new-password"
                value={form.next}
                onChange={(e) => setForm((f) => ({ ...f, next: e.target.value }))}
              />
            </Field>
            <Field id="pw-confirm" label="Ещё раз">
              <Input
                id="pw-confirm"
                type="password"
                required
                autoComplete="new-password"
                value={form.confirm}
                onChange={(e) => setForm((f) => ({ ...f, confirm: e.target.value }))}
              />
            </Field>
          </div>
          <div>
            <Button type="submit" disabled={busy || !form.current || !form.next}>
              {busy && <Loader2 className="animate-spin" />} Сменить пароль
            </Button>
          </div>
        </form>
      </CardContent>
    </Card>
  );
}

export default function ProfilePage() {
  return (
    <div className="mx-auto grid max-w-2xl gap-6">
      <h1 className="title-display text-4xl sm:text-5xl">Профиль</h1>
      <AvatarCard />
      <DetailsCard />
      <PasswordCard />
    </div>
  );
}
