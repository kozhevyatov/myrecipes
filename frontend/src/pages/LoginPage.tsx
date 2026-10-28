import { useState, type FormEvent } from "react";
import { Link, Navigate, useLocation, useNavigate } from "react-router";
import { Loader2 } from "lucide-react";
import { toast } from "sonner";
import { AuthShell } from "@/components/AuthShell";
import { Button } from "@/components/ui/button";
import { Field } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { api, setSession } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useSettings } from "@/lib/useSettings";

export default function LoginPage() {
  const { user } = useAuth();
  const { data: settings } = useSettings();
  const navigate = useNavigate();
  const location = useLocation();
  const from = (location.state as { from?: string } | null)?.from ?? "/";
  const [login, setLogin] = useState("");
  const [password, setPassword] = useState("");
  const [remember, setRemember] = useState(true);
  const [busy, setBusy] = useState(false);

  if (user) return <Navigate to={from} replace />;

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    try {
      setSession(await api.auth.login(login, password, remember));
      navigate(from, { replace: true });
    } catch (err) {
      toast.error((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <AuthShell siteName={settings?.site_name} title="С возвращением" subtitle="Войдите, чтобы открыть свои рецепты.">
      <form onSubmit={submit} className="grid gap-5">
        <Field id="login" label="Логин или email">
          <Input
            id="login"
            autoComplete="username"
            autoFocus
            required
            value={login}
            onChange={(e) => setLogin(e.target.value)}
          />
        </Field>
        <Field id="password" label="Пароль">
          <Input
            id="password"
            type="password"
            autoComplete="current-password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </Field>
        <label className="flex cursor-pointer items-center gap-2.5 text-sm font-semibold select-none">
          <input
            type="checkbox"
            className="size-4.5 accent-primary"
            checked={remember}
            onChange={(e) => setRemember(e.target.checked)}
          />
          Запомнить меня
        </label>
        <Button type="submit" size="lg" disabled={busy}>
          {busy && <Loader2 className="animate-spin" />} Войти
        </Button>
      </form>

      {settings?.registration_mode === "open" && (
        <p className="mt-6 text-center text-sm text-muted-foreground">
          Ещё нет аккаунта?{" "}
          <Link to="/register" className="font-semibold text-primary hover:underline">
            Зарегистрироваться
          </Link>
        </p>
      )}
    </AuthShell>
  );
}
