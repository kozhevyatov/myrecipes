import { useEffect } from "react";
import { Link, NavLink, Outlet, useNavigate } from "react-router";
import { BookOpen, LogOut, Moon, Settings, Sun } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Brand } from "@/components/Logo";
import { useAuth } from "@/lib/auth";
import { useSettings } from "@/lib/useSettings";
import { useTheme } from "@/lib/theme";
import { cn } from "@/lib/utils";

const navClass = ({ isActive }: { isActive: boolean }) =>
  cn(
    "flex items-center gap-2 rounded-lg px-3 py-2 text-sm font-semibold transition-colors",
    isActive ? "bg-accent text-accent-foreground" : "text-muted-foreground hover:text-foreground",
  );

export function Layout() {
  const { user, logout } = useAuth();
  const { data: settings } = useSettings();
  const { theme, toggle } = useTheme();
  const navigate = useNavigate();
  const siteName = settings?.site_name ?? "Мои рецепты";

  useEffect(() => {
    document.title = siteName;
  }, [siteName]);

  return (
    <div className="min-h-svh">
      <header className="sticky top-0 z-30 border-b bg-background/80 backdrop-blur-md">
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
                <span className="hidden px-2 text-sm font-semibold text-muted-foreground md:inline">
                  {user.display_name || user.username}
                </span>
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

      <main className="mx-auto max-w-6xl px-4 py-8 pb-24 sm:px-6 sm:pb-8">
        <Outlet />
      </main>

      {/* Нижняя навигация на телефоне */}
      <nav className="fixed inset-x-0 bottom-0 z-30 flex justify-around border-t bg-background/90 py-2 backdrop-blur-md sm:hidden">
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
