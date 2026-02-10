import type { EntanglementCluster } from "@/lib/types";

interface ClusterCardProps {
  cluster: EntanglementCluster;
}

export function ClusterCard({ cluster }: ClusterCardProps) {
  const decisions = cluster.items.filter((i) => i.type === "decision");
  const threads = cluster.items.filter((i) => i.type === "thread");

  return (
    <div className="bg-forge-card border border-forge-border rounded-lg p-4">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-semibold text-forge-text">
          Cluster #{cluster.cluster_id}
        </h3>
        <span className="text-xs text-forge-muted">
          {cluster.items.length} items &middot;{" "}
          {cluster.resonances.length} resonances
        </span>
      </div>

      {/* Projects spanned */}
      <div className="flex flex-wrap gap-1.5 mb-3">
        {cluster.projects.map((p) => (
          <span
            key={p}
            className="text-xs px-2 py-0.5 rounded bg-cross-project/10 text-cross-project border border-cross-project/20"
          >
            {p}
          </span>
        ))}
      </div>

      {/* Strongest link */}
      <div className="text-xs text-forge-muted mb-3">
        Avg similarity:{" "}
        <span className="text-forge-text font-mono">
          {cluster.avg_similarity.toFixed(3)}
        </span>
        {cluster.strongest_link && (
          <>
            {" "}&middot; Strongest:{" "}
            <span className="text-tier-high font-mono">
              {cluster.strongest_link.similarity.toFixed(3)}
            </span>
          </>
        )}
      </div>

      {/* Items grouped by type */}
      {decisions.length > 0 && (
        <div className="mb-2">
          <p className="text-xs text-forge-muted uppercase tracking-wide mb-1">
            Decisions ({decisions.length})
          </p>
          <div className="space-y-1">
            {decisions.map((d) => (
              <div
                key={d.uuid}
                className="text-xs flex items-start gap-2"
              >
                <span className="font-mono text-forge-muted shrink-0">
                  {d.local_id}
                </span>
                <span className="text-forge-text line-clamp-1">
                  {d.text}
                </span>
                <span className="text-forge-muted shrink-0 ml-auto">
                  {d.project}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {threads.length > 0 && (
        <div>
          <p className="text-xs text-forge-muted uppercase tracking-wide mb-1">
            Threads ({threads.length})
          </p>
          <div className="space-y-1">
            {threads.map((t) => (
              <div
                key={t.uuid}
                className="text-xs flex items-start gap-2"
              >
                <span className="font-mono text-forge-muted shrink-0">
                  {t.local_id}
                </span>
                <span className="text-forge-text line-clamp-1">
                  {t.text}
                </span>
                <span className="text-forge-muted shrink-0 ml-auto">
                  {t.project}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Resonance details (collapsed by default, show top 5) */}
      {cluster.resonances.length > 0 && (
        <div className="mt-3 pt-3 border-t border-forge-border/50">
          <p className="text-xs text-forge-muted uppercase tracking-wide mb-1">
            Top Resonances
          </p>
          <div className="space-y-1">
            {cluster.resonances
              .slice()
              .sort((a, b) => b.similarity - a.similarity)
              .slice(0, 5)
              .map((r, i) => (
                <div
                  key={i}
                  className="text-xs flex items-center gap-2"
                >
                  <span className="font-mono text-forge-muted">
                    {r.from.slice(0, 8)}
                  </span>
                  <span className="text-forge-muted">&rarr;</span>
                  <span className="font-mono text-forge-muted">
                    {r.to.slice(0, 8)}
                  </span>
                  <span
                    className={`font-mono ml-auto ${
                      r.tier === "strong"
                        ? "text-tier-high"
                        : "text-tier-medium"
                    }`}
                  >
                    {r.similarity.toFixed(3)}
                  </span>
                  <span
                    className={`text-xs px-1.5 py-0.5 rounded ${
                      r.tier === "strong"
                        ? "bg-tier-high/10 text-tier-high"
                        : "bg-tier-medium/10 text-tier-medium"
                    }`}
                  >
                    {r.tier}
                  </span>
                </div>
              ))}
          </div>
        </div>
      )}
    </div>
  );
}
