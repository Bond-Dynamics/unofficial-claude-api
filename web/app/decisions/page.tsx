export const dynamic = "force-dynamic";

import { api } from "@/lib/api";
import { DecisionTable } from "@/components/DecisionTable";

export default async function DecisionsPage() {
  const [decisions, conflicts] = await Promise.all([
    api.getAllDecisions(),
    api.getConflictingDecisions(),
  ]);

  const conflictUuids = new Set(conflicts.map((c) => c.uuid));

  return (
    <div>
      <h1 className="text-xl font-bold text-forge-text mb-2">
        Decision Registry
      </h1>
      <p className="text-sm text-forge-muted mb-6">
        {decisions.length} active decisions across all projects
        {conflicts.length > 0 && (
          <span className="text-tier-low ml-2">
            ({conflicts.length} with conflicts)
          </span>
        )}
      </p>

      {/* Conflict summary */}
      {conflicts.length > 0 && (
        <div className="bg-forge-card border border-tier-low/30 rounded-lg p-4 mb-6">
          <h2 className="text-sm font-semibold text-tier-low mb-2 uppercase tracking-wide">
            Decisions with Conflicts
          </h2>
          <DecisionTable decisions={conflicts} showProject />
        </div>
      )}

      {/* All decisions */}
      <div className="bg-forge-card border border-forge-border rounded-lg p-4">
        <DecisionTable decisions={decisions} showProject />
      </div>
    </div>
  );
}
