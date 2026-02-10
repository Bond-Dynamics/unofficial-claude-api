import type { EntanglementItem } from "@/lib/types";

interface LooseEndListProps {
  items: EntanglementItem[];
}

export function LooseEndList({ items }: LooseEndListProps) {
  if (items.length === 0) {
    return (
      <p className="text-sm text-forge-muted py-4">
        No loose ends — all items have cross-project resonances.
      </p>
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-forge-border text-left text-xs text-forge-muted uppercase tracking-wide">
            <th className="pb-2 pr-4">ID</th>
            <th className="pb-2 pr-4">Type</th>
            <th className="pb-2 pr-4">Text</th>
            <th className="pb-2">Project</th>
          </tr>
        </thead>
        <tbody>
          {items.map((item) => (
            <tr
              key={item.uuid}
              className="border-b border-forge-border/50 hover:bg-forge-card/50 transition-colors"
            >
              <td className="py-2.5 pr-4 font-mono text-xs text-forge-muted whitespace-nowrap">
                {item.local_id}
              </td>
              <td className="py-2.5 pr-4">
                <span
                  className={`text-xs px-1.5 py-0.5 rounded ${
                    item.type === "decision"
                      ? "bg-tier-high/10 text-tier-high"
                      : "bg-cross-project/10 text-cross-project"
                  }`}
                >
                  {item.type}
                </span>
              </td>
              <td className="py-2.5 pr-4 text-forge-text max-w-md">
                <p className="line-clamp-1">{item.text}</p>
              </td>
              <td className="py-2.5 text-xs text-forge-muted whitespace-nowrap">
                {item.project}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
