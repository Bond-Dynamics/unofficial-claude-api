import type { EntanglementBridge } from "@/lib/types";

interface BridgeListProps {
  bridges: EntanglementBridge[];
}

export function BridgeList({ bridges }: BridgeListProps) {
  if (bridges.length === 0) {
    return (
      <p className="text-sm text-forge-muted py-4">
        No lineage bridges detected.
      </p>
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-forge-border text-left text-xs text-forge-muted uppercase tracking-wide">
            <th className="pb-2 pr-4">UUID</th>
            <th className="pb-2 pr-4">Type</th>
            <th className="pb-2 pr-4">Projects</th>
            <th className="pb-2">Edges</th>
          </tr>
        </thead>
        <tbody>
          {bridges.map((b) => (
            <tr
              key={b.uuid}
              className="border-b border-forge-border/50 hover:bg-forge-card/50 transition-colors"
            >
              <td className="py-2.5 pr-4 font-mono text-xs text-forge-muted">
                {b.uuid.slice(0, 12)}...
              </td>
              <td className="py-2.5 pr-4">
                <span
                  className={`text-xs px-1.5 py-0.5 rounded ${
                    b.type === "decision"
                      ? "bg-tier-high/10 text-tier-high"
                      : "bg-cross-project/10 text-cross-project"
                  }`}
                >
                  {b.type}
                </span>
              </td>
              <td className="py-2.5 pr-4">
                <div className="flex flex-wrap gap-1">
                  {b.projects.map((p) => (
                    <span
                      key={p}
                      className="text-xs text-forge-muted"
                    >
                      {p}
                    </span>
                  ))}
                </div>
              </td>
              <td className="py-2.5 font-mono text-xs text-forge-text">
                {b.edge_count}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
