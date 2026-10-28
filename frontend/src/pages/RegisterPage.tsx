import { useState, type ChangeEvent, type FormEvent } from "react";
import { Link, Navigate, useNavigate } from "react-router";
import { Loader2, Lock } from "lucide-react";
import { toast } from "sonner";
import { AuthShell } from "@/components/AuthShell";
import { Button } from "@/components/ui/button";
import { Field } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { api, setSession } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useSettings } from "@/lib/useSettings";

export default function RegisterPage() {
  const { user } = useAuth();
  const { data: settings, isLoading } = useSettings();
  const navigate = useNavigate();
  const [form, setForm] = useState({ username: "", display_name: "", email: "", password: "", confirm: "" });
  const [busy, setBusy] = useState(false);

  if (user) return <Navigate to="/" replace />;
  if (isLoading) return null;

  const set = (k: keyof typeof form) => (e: ChangeEvent<HTMLInputElement>) =>
    setForm((f) => ({ ...f, [k]: e.target.value }));

  if (settings?.registration_mode !== "open") {
    return (
      <AuthShell siteName={settings?.site_name} title="Регистрация закрыта">
        <div className="flex gap-4 rounded-2xl border bg-card p-5">
          <Lock className="mt-0.5 size-5 shrink-0 text-muted-foreground" />
          <p className="text-sm text-muted-foreground">
            Администратор отключил свободную регистрацию. Попросите его создать вам доступ или открыть регистрацию.
          </p>
        </div>
        <Button asChild variant="outline" className="mt-6 w-full">
          <Link to="/login">Ко входу</Link>
        </Button>
      </AuthShell>
    );
  }

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (form.password !== form.confirm) return toast.error("Пароли не совпадают");
    setBusy(true);
    try {
      const { username, display_name, email, password } = form;
      setSession(await api.auth.register({ username, display_name, email, password }));
      navigate("/", { replace: true });
    } catch (err) {
      toast.error((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <AuthShell siteName={settings?.site_name} title="Создать аккаунт" subtitle="Пара секунд — и можно записывать рецепты.">
      <form onSubmit={submit} className="grid gap-5">
        <div className="grid gap-5 sm:grid-cols-2">
          <Field id="username" label="Логин" hint="Латиница, цифры, _ . -">
            <Input id="username" required autoComplete="username" value={form.username} onChange={set("username")} />
          </Field>
          <Field id="display_name" label="Имя">
            <Input id="display_name" autoComplete="name" value={form.display_name} onChange={set("display_name")} />
          </Field>
        </div>
        <Field id="email" label="Email">
          <Input id="email" type="email" required autoComplete="email" value={form.email} onChange={set("email")} />
        </Field>
        <div className="grid gap-5 sm:grid-cols-2">
          <Field id="password" label="Пароль" hint="Минимум 8 символов">
            <Input
              id="password"
              type="password"
              required
              minLength={8}
              autoComplete="new-password"
              value={form.password}
              onChange={set("password")}
            />
          </Field>
          <Field id="confirm" label="Ещё раз">
            <Input
              id="confirm"
              type="password"
              required
              autoComplete="new-password"
              value={form.confirm}
              onChange={set("confirm")}
            />
          </Field>
        </div>
        <Button type="submit" size="lg" disabled={busy} className="mt-2">
          {busy && <Loader2 className="animate-spin" />} Зарегистрироваться
        </Button>
      </form>
      <p className="mt-6 text-center text-sm text-muted-foreground">
        Уже есть аккаунт?{" "}
        <Link to="/login" className="font-semibold text-primary hover:underline">
          Войти
        </Link>
      </p>
    </AuthShell>
  );
}
