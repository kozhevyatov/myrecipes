import { useState, type ChangeEvent, type FormEvent, type ReactNode } from "react";
import { useNavigate } from "react-router";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, CheckCircle2, Database, HardDrive, KeyRound, Loader2, Server } from "lucide-react";
import { toast } from "sonner";
import { AuthShell } from "@/components/AuthShell";
import { Button } from "@/components/ui/button";
import { Field } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { api, setSession, type DatabaseConfig, type SetupStatus } from "@/lib/api";
import { cn } from "@/lib/utils";

type Step = "database" | "admin";

function Stepper({ step, dbLocked }: { step: Step; dbLocked: boolean }) {
  const items: { key: Step; label: string }[] = [
    { key: "database", label: "База данных" },
    { key: "admin", label: "Администратор" },
  ];
  return (
    <ol className="mb-8 flex items-center gap-3">
      {items.map((it, i) => {
        const done = (it.key === "database" && (step === "admin" || dbLocked)) || false;
        const active = it.key === step;
        return (
          <li key={it.key} className="flex items-center gap-3">
            {i > 0 && <span className="h-px w-8 bg-border" />}
            <span
              className={cn(
                "flex size-7 items-center justify-center rounded-full text-xs font-bold",
                done && "bg-success text-white",
                active && !done && "bg-primary text-primary-foreground",
                !active && !done && "bg-muted text-muted-foreground",
              )}
            >
              {done ? <Check className="size-4" /> : i + 1}
            </span>
            <span className={cn("text-sm font-semibold", !active && "text-muted-foreground")}>{it.label}</span>
          </li>
        );
      })}
    </ol>
  );
}

function OptionCard({
  selected,
  onClick,
  icon,
  title,
  text,
}: {
  selected: boolean;
  onClick: () => void;
  icon: ReactNode;
  title: string;
  text: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "flex flex-col items-start gap-2 rounded-2xl border-2 bg-card p-4 text-left transition-all",
        selected ? "border-primary shadow-sm" : "border-transparent ring-1 ring-border hover:ring-primary/40",
      )}
    >
      <span className={cn("rounded-lg p-2", selected ? "bg-primary text-primary-foreground" : "bg-muted")}>{icon}</span>
      <span className="font-bold">{title}</span>
      <span className="text-xs text-muted-foreground">{text}</span>
    </button>
  );
}

function DatabaseStep({ token, onDone }: { token: string; onDone: () => void }) {
  const [cfg, setCfg] = useState<DatabaseConfig>({
    type: "sqlite",
    host: "mysql",
    port: 3306,
    user: "recipes",
    password: "",
    database: "recipes",
  });
  const [tested, setTested] = useState(false);
  const [busy, setBusy] = useState<"test" | "save" | null>(null);

  const set = (k: keyof DatabaseConfig) => (e: ChangeEvent<HTMLInputElement>) => {
    setTested(false);
    setCfg((c) => ({ ...c, [k]: k === "port" ? Number(e.target.value) || undefined : e.target.value }));
  };

  const test = async () => {
    setBusy("test");
    try {
      await api.setup.testDb(cfg, token);
      setTested(true);
      toast.success("Подключение работает");
    } catch (err) {
      toast.error((err as Error).message);
    } finally {
      setBusy(null);
    }
  };

  const save = async (e: FormEvent) => {
    e.preventDefault();
    setBusy("save");
    try {
      await api.setup.database(cfg, token);
      toast.success("База данных готова");
      onDone();
    } catch (err) {
      toast.error((err as Error).message);
    } finally {
      setBusy(null);
    }
  };

  return (
    <form onSubmit={save} className="grid gap-6">
      <div className="grid grid-cols-2 gap-3">
        <OptionCard
          selected={cfg.type === "sqlite"}
          onClick={() => setCfg((c) => ({ ...c, type: "sqlite" }))}
          icon={<HardDrive className="size-5" />}
          title="SQLite"
          text="Файл внутри тома /data. Ничего настраивать не нужно."
        />
        <OptionCard
          selected={cfg.type === "mysql"}
          onClick={() => {
            setTested(false);
            setCfg((c) => ({ ...c, type: "mysql" }));
          }}
          icon={<Server className="size-5" />}
          title="MySQL / MariaDB"
          text="Свой сервер или контейнер из docker-compose."
        />
      </div>

      {cfg.type === "mysql" && (
        <div className="grid gap-4 rounded-2xl border bg-card p-5">
          <div className="grid grid-cols-[1fr_6rem] gap-3">
            <Field id="host" label="Хост" hint="Для контейнера из compose — mysql">
              <Input id="host" required value={cfg.host ?? ""} onChange={set("host")} />
            </Field>
            <Field id="port" label="Порт">
              <Input id="port" type="number" value={cfg.port ?? ""} onChange={set("port")} />
            </Field>
          </div>
          <Field id="database" label="Имя базы">
            <Input id="database" required value={cfg.database ?? ""} onChange={set("database")} />
          </Field>
          <div className="grid grid-cols-2 gap-3">
            <Field id="user" label="Пользователь">
              <Input id="user" required autoComplete="off" value={cfg.user ?? ""} onChange={set("user")} />
            </Field>
            <Field id="dbpass" label="Пароль">
              <Input
                id="dbpass"
                type="password"
                autoComplete="new-password"
                value={cfg.password ?? ""}
                onChange={set("password")}
              />
            </Field>
          </div>
          <Button type="button" variant="outline" onClick={test} disabled={busy !== null}>
            {busy === "test" ? <Loader2 className="animate-spin" /> : tested ? <CheckCircle2 className="text-success" /> : <Database />}
            {tested ? "Подключение проверено" : "Проверить подключение"}
          </Button>
        </div>
      )}

      <Button type="submit" size="lg" disabled={busy !== null}>
        {busy === "save" && <Loader2 className="animate-spin" />} Далее
      </Button>
    </form>
  );
}

function AdminStep({ token }: { token: string }) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [form, setForm] = useState({
    username: "admin",
    display_name: "",
    email: "",
    password: "",
    confirm: "",
    site_name: "Мои рецепты",
  });
  const [openRegistration, setOpenRegistration] = useState(false);
  const [busy, setBusy] = useState(false);

  const set = (k: keyof typeof form) => (e: ChangeEvent<HTMLInputElement>) =>
    setForm((f) => ({ ...f, [k]: e.target.value }));

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (form.password !== form.confirm) return toast.error("Пароли не совпадают");
    setBusy(true);
    try {
      const res = await api.setup.admin(
        {
          username: form.username,
          display_name: form.display_name,
          email: form.email,
          password: form.password,
          site_name: form.site_name,
          registration_mode: openRegistration ? "open" : "closed",
        },
        token,
      );
      setSession(res);
      queryClient.setQueryData<SetupStatus>(["setup-status"], (s) => (s ? { ...s, setup_complete: true } : s));
      queryClient.invalidateQueries({ queryKey: ["settings"] });
      toast.success("Готово! Добро пожаловать.");
      navigate("/", { replace: true });
    } catch (err) {
      toast.error((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={submit} className="grid gap-5">
      <div className="grid gap-5 sm:grid-cols-2">
        <Field id="username" label="Логин" hint="Латиница, цифры, _ . -">
          <Input id="username" required autoComplete="username" value={form.username} onChange={set("username")} />
        </Field>
        <Field id="display_name" label="Имя">
          <Input id="display_name" value={form.display_name} onChange={set("display_name")} />
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
          <Input id="confirm" type="password" required autoComplete="new-password" value={form.confirm} onChange={set("confirm")} />
        </Field>
      </div>

      <div className="mt-2 grid gap-5 border-t pt-6">
        <Field id="site_name" label="Название сервиса">
          <Input id="site_name" required value={form.site_name} onChange={set("site_name")} />
        </Field>
        <label className="flex cursor-pointer items-start justify-between gap-4 rounded-2xl border bg-card p-4">
          <span>
            <span className="block font-semibold">Свободная регистрация</span>
            <span className="text-sm text-muted-foreground">
              Любой сможет создать аккаунт. Можно поменять позже в управлении.
            </span>
          </span>
          <Switch checked={openRegistration} onCheckedChange={setOpenRegistration} />
        </label>
      </div>

      <Button type="submit" size="lg" disabled={busy} className="mt-2">
        {busy && <Loader2 className="animate-spin" />} Завершить настройку
      </Button>
    </form>
  );
}

export default function SetupPage() {
  const status = useQuery({ queryKey: ["setup-status"], queryFn: api.setup.status });
  const [dbDone, setDbDone] = useState(false);
  const [token, setToken] = useState("");

  const dbConfigured = Boolean(status.data?.database_configured) || dbDone;
  const step: Step = dbConfigured ? "admin" : "database";

  return (
    <AuthShell
      title={step === "database" ? "Первый запуск" : "Учётная запись администратора"}
      subtitle={
        step === "database"
          ? "Выберите, где хранить рецепты. SQLite подойдёт для дома и небольшой семьи."
          : "Этот пользователь сможет управлять сервисом и регистрацией."
      }
    >
      <Stepper step={step} dbLocked={Boolean(status.data?.database_from_env)} />

      {status.data?.setup_token_required && (
        <div className="mb-6">
          <Field id="setup_token" label="Токен настройки" hint="Значение SETUP_TOKEN из docker-compose">
            <div className="relative">
              <KeyRound className="absolute top-1/2 left-3.5 size-4 -translate-y-1/2 text-muted-foreground" />
              <Input id="setup_token" className="pl-10" value={token} onChange={(e) => setToken(e.target.value)} />
            </div>
          </Field>
        </div>
      )}

      {step === "database" ? <DatabaseStep token={token} onDone={() => setDbDone(true)} /> : <AdminStep token={token} />}
    </AuthShell>
  );
}
