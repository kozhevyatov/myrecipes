import { useEffect } from "react";
import { Link, NavLink, Outlet, useLocation, useNavigate } from "react-router";
import { BookOpen, LogOut, Moon, Settings, Sun } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Avatar } from "@/components/Avatar";
import { Brand } from "@/components/Logo";
import { useAuth } from "@/lib/auth";
import { useSettings } from "@/lib/useSettings";
import { useTheme } from "@/lib/theme";
import { cn } from "@/lib/utils";

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
  useEffect(() => {
    if (!location.pathname.startsWith("/recipes/") || location.pathname.endsWith("/new")) document.title = siteName;
  }, [siteName, location.pathname]);

  return (
    <div className="min-h-svh">
      <header className="sticky top-0 z-30 border-b border-transparent bg-background/75 backdrop-blur-xl supports-[backdrop-filter]:border-border/60">
        <div className="mx-auto flex h-16 max-w-6xl items-center gap-4 px-4 sm:px-6">
          <Link to="/" className="shrink-0">
            <Brand name={siteName} />
          </Link>

          <nav className="ml-4 hidden items-center gap-1 sm:flex">
            <NavLink to="/" end className={navClass}>
              <BookOpen className="size-4" /> Рецепты
            </NavLink>
            {user?.is_admin && (
              <NavLink to="/admin" className={navClass}>
                <Settings className="size-4" /> Управление
              </NavLink>
            )}
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

      <main className="mx-auto max-w-6xl px-4 py-8 pb-28 sm:px-6 sm:py-10 sm:pb-12">
        <Outlet />
      </main>

      {/* Нижняя навигация на телефоне */}
      <nav className="fixed inset-x-0 bottom-0 z-30 flex justify-center gap-2 border-t bg-background/85 px-4 pt-2 pb-[max(0.5rem,env(safe-area-inset-bottom))] backdrop-blur-xl sm:hidden">
        <NavLink to="/" end className={navClass}>
          <BookOpen className="size-4" /> Рецепты
        </NavLink>
        {user?.is_admin && (
          <NavLink to="/admin" className={navClass}>
            <Settings className="size-4" /> Управление
          </NavLink>
        )}
      </nav>
    </div>
  );
}
