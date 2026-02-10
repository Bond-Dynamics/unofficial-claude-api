import type { Thread } from "@/lib/types";
import { StaleBadge } from "./StaleBadge";

interface ThreadTableProps {
  threads: Thread[];
  showProject?: boolean;
}

const STATUS_COLORS: Record<string, string> = {
  open: "text-status-active",
  resolved: "text-status-resolved",
  blocked: "text-status-blocked",
};

const PRIORITY_COLORS: Record<string, string> = {
  high: "bg-tier-low/20 text-tier-low",
  medium: "bg-tier-medium/20 text-tier-medium",
  low: "bg-gray-800 text-gray-400",
};

export function ThreadTable({ threads, showProject = false }: ThreadTableProps) {
  if (threads.length === 0) {
    return <p className="text-sm text-forge-muted py-4">No active threads.</p>;
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-forge-border text-left text-xs text-forge-muted uppercase tracking-wide">
            <th className="pb-2 pr-4">ID</th>
            {showProject && <th className="pb-2 pr-4">Project</th>}
            <th className="pb-2 pr-4">Title</th>
            <th className="pb-2 pr-4">Status</th>
            <th className="pb-2 pr-4">Priority</th>
            <th className="pb-2 pr-4">Blocked By</th>
            <th className="pb-2">Staleness</th>
          </tr>
        </thead>
        <tbody>
          {threads.map((t) => (
            <tr
              key={t.uuid}
              className="border-b border-forge-border/50 hover:bg-forge-card/50 transition-colors"
            >
              <td className="py-3 pr-4 font-mono text-xs text-forge-muted whitespace-nowrap">
                {t.local_id}
              </td>
              {showProject && (
                <td className="py-3 pr-4 text-xs text-forge-muted whitespace-nowrap">
                  {t.project}
                </td>
              )}
              <td className="py-3 pr-4 text-forge-text max-w-md">
                <p className="line-clamp-2">{t.title}</p>
                {t.resolution && (
                  <p className="text-xs text-forge-muted mt-1 line-clamp-1">
                    {t.resolution}
                  </p>
                )}
              </td>
              <td className="py-3 pr-4">
                <span className={`text-xs ${STATUS_COLORS[t.status] ?? "text-forge-muted"}`}>
                  {t.status}
                </span>
              </td>
              <td className="py-3 pr-4">
                <span
                  className={`inline-flex items-center px-2 py-0.5 rounded text-xs ${
                    PRIORITY_COLORS[t.priority] ?? "text-forge-muted"
                  }`}
                >
                  {t.priority}
                </span>
              </td>
              <td className="py-3 pr-4 font-mono text-xs text-forge-muted">
                {t.blocked_by?.length > 0 ? (
                  <span className="text-status-blocked">
                    {t.blocked_by.length} blocker{t.blocked_by.length > 1 ? "s" : ""}
                  </span>
                ) : (
                  "—"
                )}
              </td>
              <td className="py-3">
                <StaleBadge hops={t.hops_since_validated} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
