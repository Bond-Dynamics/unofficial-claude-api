import type { Decision } from "@/lib/types";
import { EpistemicTierBadge } from "./EpistemicTierBadge";
import { ConflictBadge } from "./ConflictBadge";
import { StaleBadge } from "./StaleBadge";

interface DecisionTableProps {
  decisions: Decision[];
  showProject?: boolean;
}

export function DecisionTable({ decisions, showProject = false }: DecisionTableProps) {
  if (decisions.length === 0) {
    return <p className="text-sm text-forge-muted py-4">No active decisions.</p>;
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-forge-border text-left text-xs text-forge-muted uppercase tracking-wide">
            <th className="pb-2 pr-4">ID</th>
            {showProject && <th className="pb-2 pr-4">Project</th>}
            <th className="pb-2 pr-4">Decision</th>
            <th className="pb-2 pr-4">Tier</th>
            <th className="pb-2 pr-4">Status</th>
            <th className="pb-2 pr-4">Conflicts</th>
            <th className="pb-2">Staleness</th>
          </tr>
        </thead>
        <tbody>
          {decisions.map((d) => (
            <tr
              key={d.uuid}
              className="border-b border-forge-border/50 hover:bg-forge-card/50 transition-colors"
            >
              <td className="py-3 pr-4 font-mono text-xs text-forge-muted whitespace-nowrap">
                {d.local_id}
              </td>
              {showProject && (
                <td className="py-3 pr-4 text-xs text-forge-muted whitespace-nowrap">
                  {d.project}
                </td>
              )}
              <td className="py-3 pr-4 text-forge-text max-w-md">
                <p className="line-clamp-2">{d.text}</p>
                {d.rationale && (
                  <p className="text-xs text-forge-muted mt-1 line-clamp-1">
                    {d.rationale}
                  </p>
                )}
              </td>
              <td className="py-3 pr-4">
                <EpistemicTierBadge tier={d.epistemic_tier} />
              </td>
              <td className="py-3 pr-4">
                <span
                  className={`text-xs ${
                    d.status === "active"
                      ? "text-status-active"
                      : "text-status-resolved"
                  }`}
                >
                  {d.status}
                </span>
              </td>
              <td className="py-3 pr-4">
                <ConflictBadge count={d.conflicts_with?.length ?? 0} />
              </td>
              <td className="py-3">
                <StaleBadge hops={d.hops_since_validated} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
