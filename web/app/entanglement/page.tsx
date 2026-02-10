export const dynamic = "force-dynamic";

import { Network, GitFork, AlertCircle, Zap } from "lucide-react";
import { api } from "@/lib/api";
import { StatsCard } from "@/components/StatsCard";
import { ClusterCard } from "@/components/ClusterCard";
import { BridgeList } from "@/components/BridgeList";
import { LooseEndList } from "@/components/LooseEndList";
import type { EntanglementScan } from "@/lib/types";

async function getScanData(): Promise<EntanglementScan | null> {
  try {
    return await api.getEntanglement();
  } catch {
    return null;
  }
}

export default async function EntanglementPage() {
  const scan = await getScanData();

  if (!scan) {
    return (
      <div>
        <h1 className="text-xl font-bold text-forge-text mb-2">
          Entanglement Discovery
        </h1>
        <div className="bg-forge-card border border-forge-border rounded-lg p-8 text-center">
          <Network size={32} className="text-forge-muted mx-auto mb-3" />
          <p className="text-sm text-forge-muted mb-1">
            No entanglement scan data available.
          </p>
          <p className="text-xs text-forge-muted">
            Run{" "}
            <code className="text-forge-text bg-forge-surface px-1.5 py-0.5 rounded">
              python scripts/run_entanglement.py
            </code>{" "}
            or POST to{" "}
            <code className="text-forge-text bg-forge-surface px-1.5 py-0.5 rounded">
              /api/entanglement/scan
            </code>{" "}
            to generate a scan.
          </p>
        </div>
      </div>
    );
  }

  const scannedDate = new Date(scan.scanned_at).toLocaleString();

  return (
    <div>
      <div className="flex items-center justify-between mb-2">
        <h1 className="text-xl font-bold text-forge-text">
          Entanglement Discovery
        </h1>
        <span className="text-xs text-forge-muted">
          Scanned {scannedDate}
        </span>
      </div>
      <p className="text-sm text-forge-muted mb-6">
        Cross-project semantic resonances across{" "}
        {scan.decisions_scanned} decisions and {scan.threads_scanned} threads
      </p>

      {/* Stats row */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-4 mb-8">
        <StatsCard
          label="Resonances"
          value={scan.resonances_found}
          icon={<Network size={16} />}
        />
        <StatsCard
          label="Clusters"
          value={scan.clusters.length}
          icon={<Zap size={16} />}
        />
        <StatsCard
          label="Bridges"
          value={scan.bridges.length}
          icon={<GitFork size={16} />}
        />
        <StatsCard
          label="Loose Ends"
          value={scan.loose_ends.length}
          icon={<AlertCircle size={16} />}
        />
        <StatsCard
          label="Strong"
          value={scan.by_tier.strong}
          icon={<span className="text-tier-high text-xs font-bold">&ge;.65</span>}
        />
        <StatsCard
          label="Weak"
          value={scan.by_tier.weak}
          icon={<span className="text-tier-medium text-xs font-bold">&ge;.50</span>}
        />
      </div>

      {/* Clusters */}
      <section className="mb-8">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-sm font-semibold text-forge-text uppercase tracking-wide">
            Entanglement Clusters
          </h2>
          <span className="text-xs text-forge-muted">
            {scan.clusters.length} cluster{scan.clusters.length !== 1 ? "s" : ""}
          </span>
        </div>
        {scan.clusters.length === 0 ? (
          <p className="text-sm text-forge-muted">
            No clusters found at this similarity threshold.
          </p>
        ) : (
          <div className="grid grid-cols-1 gap-4">
            {scan.clusters.map((c) => (
              <ClusterCard key={c.cluster_id} cluster={c} />
            ))}
          </div>
        )}
      </section>

      {/* Bridges */}
      <section className="mb-8">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-sm font-semibold text-forge-text uppercase tracking-wide">
            Lineage Bridges
          </h2>
          <span className="text-xs text-forge-muted">
            {scan.bridges.length} bridge{scan.bridges.length !== 1 ? "s" : ""}
          </span>
        </div>
        <div className="bg-forge-card border border-forge-border rounded-lg p-4">
          <BridgeList bridges={scan.bridges} />
        </div>
      </section>

      {/* Loose Ends */}
      <section>
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-sm font-semibold text-forge-text uppercase tracking-wide">
            Loose Ends
          </h2>
          <span className="text-xs text-forge-muted">
            {scan.loose_ends.length} item{scan.loose_ends.length !== 1 ? "s" : ""}
          </span>
        </div>
        <div className="bg-forge-card border border-forge-border rounded-lg p-4">
          <LooseEndList items={scan.loose_ends} />
        </div>
      </section>
    </div>
  );
}
