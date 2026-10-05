import { NavLink } from "react-router-dom";
import { Download, Library, Search, Settings } from "lucide-react";
import { cn } from "@/lib/utils";

const items = [
  { to: "/search", label: "Search", icon: Search },
  { to: "/library", label: "Library", icon: Library },
  { to: "/downloads", label: "Downloads", icon: Download },
  { to: "/settings", label: "Settings", icon: Settings },
];

export function Sidebar() {
  return (
    <aside className="flex w-60 shrink-0 flex-col gap-2 max-md:w-16">
      <div className="rounded-lg bg-surface px-3 py-4">
        <div className="mb-4 flex items-center gap-2 px-3 max-md:justify-center max-md:px-0">
          <img src="/favicon.svg" alt="" className="h-7 w-7" />
          <span className="text-lg font-extrabold tracking-tight max-md:hidden">Ofy</span>
        </div>
        <nav className="flex flex-col gap-1">
          {items.map(({ to, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              className={({ isActive }) =>
                cn(
                  "flex items-center gap-4 rounded-md px-3 py-2 text-sm font-bold text-muted-foreground transition-colors hover:text-foreground max-md:justify-center",
                  isActive && "bg-elevated text-foreground",
                )
              }
            >
              <Icon className="h-5 w-5" />
              <span className="max-md:hidden">{label}</span>
            </NavLink>
          ))}
        </nav>
      </div>
      <div className="flex-1 rounded-lg bg-surface" />
    </aside>
  );
}
