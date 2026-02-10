export const dynamic = "force-dynamic";

import { api } from "@/lib/api";
import { ThreadTable } from "@/components/ThreadTable";

export default async function ThreadsPage() {
  const threads = await api.getAllThreads();

  const blockedCount = threads.filter(
    (t) => t.status === "blocked"
  ).length;
  const staleCount = threads.filter(
    (t) => t.hops_since_validated >= 3
  ).length;

  return (
    <div>
      <h1 className="text-xl font-bold text-forge-text mb-2">
        Thread Registry
      </h1>
      <p className="text-sm text-forge-muted mb-6">
        {threads.length} active threads across all projects
        {blockedCount > 0 && (
          <span className="text-status-blocked ml-2">
            ({blockedCount} blocked)
          </span>
        )}
        {staleCount > 0 && (
          <span className="text-tier-medium ml-2">
            ({staleCount} stale)
          </span>
        )}
      </p>

      <div className="bg-forge-card border border-forge-border rounded-lg p-4">
        <ThreadTable threads={threads} showProject />
      </div>
    </div>
  );
}
