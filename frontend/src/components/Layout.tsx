import { useEffect } from "react";
import { Link, NavLink, Outlet, useLocation, useNavigate } from "react-router";
import { useQuery } from "@tanstack/react-query";
import { BookOpen, Carrot, LogOut, Moon, Settings, ShoppingBasket, Sun } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Avatar } from "@/components/Avatar";
import { Brand } from "@/components/Logo";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useSettings } from "@/lib/useSettings";
import { useTheme } from "@/lib/theme";
import { cn } from "@/lib/utils";

const tabClass = ({ isActive }: { isActive: boolean }) =>
  cn(
    "relative flex flex-1 flex-col items-center gap-0.5 rounded-xl py-1.5 text-[11px] font-medium transition-colors",
    isActive ? "text-primary" : "text-muted-foreground",
  );

const navClass = ({ isActive }: { isActive: boolean }) =>
  cn(
    "flex items-center gap-2 rounded-full px-3.5 py-1.5 text-sm font-medium transition-colors",
    isActive ? "bg-foreground text-background" : "text-muted-foreground hover:text-foreground",
  );

export function Layout() {
  const { user, logout } = useAuth();
  const { data: settings } = useSettings();
  const { theme, toggle } = useTheme();
  const navigate = useNavigate();
  const siteName = settings?.site_name ?? "Мои рецепты";

  const location = useLocation();
  const shopping = useQuery({ queryKey: ["shopping-lists"], queryFn: api.shopping.lists, enabled: Boolean(user) });
  const toBuy = shopping.data?.reduce((n, l) => n + l.todo, 0) ?? 0;
  const nav = [
    { to: "/", label: "Рецепты", icon: BookOpen, end: true },
    { to: "/shopping", label: "Покупки", icon: ShoppingBasket, badge: toBuy },
    { to: "/products", label: "Продукты", icon: Carrot },
    ...(user?.is_admin ? [{ to: "/admin", label: "Управление", icon: Settings }] : []),
  ];
  useEffect(() => {
    if (!location.pathname.startsWith("/recipes/") || location.pathname.endsWith("/new")) document.title = siteName;
  }, [siteName, location.pathname]);

  return (
    <div className="min-h-svh">
      <header className="sticky top-0 z-30 print:hidden border-b border-transparent bg-background/75 backdrop-blur-xl supports-[backdrop-filter]:border-border/60">
        <div className="mx-auto flex h-16 max-w-6xl items-center gap-4 px-4 sm:px-6">
          <Link to="/" className="shrink-0">
            <Brand name={siteName} />
          </Link>

          <nav className="ml-4 hidden items-center gap-1 sm:flex">
            {nav.map(({ to, label, icon: Icon, end, badge }) => (
              <NavLink key={to} to={to} end={end} className={navClass}>
                <Icon className="size-4" /> {label}
                {badge ? (
                  <span className="rounded-full bg-primary px-1.5 text-[11px] leading-[18px] font-semibold text-primary-foreground tabular-nums">
                    {badge}
                  </span>
                ) : null}
              </NavLink>
            ))}
          </nav>

          <div className="ml-auto flex items-center gap-1">
            <Button variant="ghost" size="icon" onClick={toggle} aria-label="Сменить тему">
              {theme === "dark" ? <Sun /> : <Moon />}
            </Button>
            {user && (
              <>
                <Link
                  to="/profile"
                  className="flex items-center gap-2 rounded-full py-1 pr-1 pl-1 text-sm text-muted-foreground transition-colors outline-none hover:bg-muted hover:text-foreground focus-visible:ring-4 focus-visible:ring-ring md:pr-3"
                  aria-label="Профиль"
                >
                  <Avatar src={user.avatar_url} name={user.display_name || user.username} className="size-8 text-xs" />
                  <span className="hidden md:inline">{user.display_name || user.username}</span>
                </Link>
                <Button
                  variant="ghost"
                  size="icon"
                  aria-label="Выйти"
                  onClick={async () => {
                    await logout();
                    navigate("/login");
                  }}
                >
                  <LogOut />
                </Button>
              </>
            )}
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-6xl px-4 py-8 pb-28 sm:px-6 sm:py-10 sm:pb-12 print:p-0">
        <Outlet />
      </main>

      {/* Нижняя навигация на телефоне */}
      <nav className="fixed inset-x-0 bottom-0 z-30 flex gap-1 print:hidden border-t bg-background/90 px-2 pt-1.5 pb-[max(0.375rem,env(safe-area-inset-bottom))] backdrop-blur-xl sm:hidden">
        {nav.map(({ to, label, icon: Icon, end, badge }) => (
          <NavLink key={to} to={to} end={end} className={tabClass}>
            <span className="relative">
              <Icon className="size-[22px]" strokeWidth={1.75} />
              {badge ? (
                <span className="absolute -top-1.5 -right-2.5 min-w-[18px] rounded-full bg-primary px-1 text-center text-[10px] leading-[18px] font-semibold text-primary-foreground tabular-nums">
                  {badge}
                </span>
              ) : null}
            </span>
            {label}
          </NavLink>
        ))}
      </nav>
    </div>
  );
}
