"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  LayoutDashboard,
  GitFork,
  Scale,
  MessageSquare,
  Search,
  Network,
} from "lucide-react";

const NAV_ITEMS = [
  { href: "/", label: "Overview", icon: LayoutDashboard },
  { href: "/lineage", label: "Lineage", icon: GitFork },
  { href: "/decisions", label: "Decisions", icon: Scale },
  { href: "/threads", label: "Threads", icon: MessageSquare },
  { href: "/entanglement", label: "Entanglement", icon: Network },
  { href: "/search", label: "Search", icon: Search },
];

export function Sidebar() {
  const pathname = usePathname();

  return (
    <aside className="fixed left-0 top-0 h-screen w-56 bg-forge-surface border-r border-forge-border flex flex-col z-10">
      <div className="p-5 border-b border-forge-border">
        <h1 className="text-sm font-bold tracking-widest text-forge-text uppercase">
          Mission Control
        </h1>
        <p className="text-xs text-forge-muted mt-1">Forge OS</p>
      </div>

      <nav className="flex-1 py-4">
        {NAV_ITEMS.map(({ href, label, icon: Icon }) => {
          const isActive =
            href === "/" ? pathname === "/" : pathname.startsWith(href);

          return (
            <Link
              key={href}
              href={href}
              className={`flex items-center gap-3 px-5 py-2.5 text-sm transition-colors ${
                isActive
                  ? "text-forge-text bg-forge-card border-r-2 border-tier-high"
                  : "text-forge-muted hover:text-forge-text hover:bg-forge-card/50"
              }`}
            >
              <Icon size={16} />
              {label}
            </Link>
          );
        })}
      </nav>

      <div className="p-5 border-t border-forge-border">
        <p className="text-xs text-forge-muted">Layer 0-4 DAG Interface</p>
      </div>
    </aside>
  );
}
