import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, Shield, UserRound } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Field } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { api, type PublicSettings, type User } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useSettings } from "@/lib/useSettings";
import { cn } from "@/lib/utils";

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

function UsersCard() {
  const { user: me } = useAuth();
  const queryClient = useQueryClient();
  const users = useQuery({ queryKey: ["admin-users"], queryFn: api.admin.users });

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
        <CardTitle>Пользователи</CardTitle>
        <CardDescription>Права администратора и блокировка.</CardDescription>
      </CardHeader>
      <CardContent className="p-0 pt-4">
        {users.isLoading ? (
          <div className="flex justify-center p-8">
            <Loader2 className="size-5 animate-spin text-muted-foreground" />
          </div>
        ) : (
          <ul className="divide-y">
            {users.data?.map((u) => (
              <li key={u.id} className={cn("flex flex-wrap items-center gap-4 px-6 py-4", !u.is_active && "opacity-55")}>
                <span className="flex size-10 items-center justify-center rounded-full bg-accent text-accent-foreground">
                  {u.is_admin ? <Shield className="size-5" /> : <UserRound className="size-5" />}
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
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

export default function AdminPage() {
  return (
    <div className="grid gap-8">
      <h1 className="text-3xl font-extrabold sm:text-4xl">Управление</h1>
      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.3fr)]">
        <SettingsCard />
        <UsersCard />
      </div>
    </div>
  );
}
