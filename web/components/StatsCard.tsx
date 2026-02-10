import type { ReactNode } from "react";

interface StatsCardProps {
  label: string;
  value: number;
  icon?: ReactNode;
}

export function StatsCard({ label, value, icon }: StatsCardProps) {
  return (
    <div className="bg-forge-card border border-forge-border rounded-lg p-4 flex flex-col gap-1">
      <div className="flex items-center justify-between">
        <span className="text-2xl font-bold text-forge-text tabular-nums">
          {value.toLocaleString()}
        </span>
        {icon && <span className="text-forge-muted">{icon}</span>}
      </div>
      <span className="text-xs text-forge-muted uppercase tracking-wide">
        {label}
      </span>
    </div>
  );
}
