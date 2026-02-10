export const dynamic = "force-dynamic";

import {
  MessageSquare,
  FolderOpen,
  Scale,
  GitFork,
  Flag,
  Network,
} from "lucide-react";
import { api } from "@/lib/api";
import { StatsCard } from "@/components/StatsCard";
import { ProjectCard } from "@/components/ProjectCard";

export default async function Dashboard() {
  const [stats, projects, alerts] = await Promise.all([
    api.getStats(),
    api.getProjects(),
    api.getAlerts(),
  ]);

  return (
    <div>
      <h1 className="text-xl font-bold tracking-wide text-forge-text mb-6">
        MISSION CONTROL
      </h1>

      {/* Stats row */}
      <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-7 gap-4 mb-8">
        <StatsCard
          label="Conversations"
          value={stats.conversations}
          icon={<MessageSquare size={16} />}
        />
        <StatsCard
          label="Projects"
          value={stats.projects}
          icon={<FolderOpen size={16} />}
        />
        <StatsCard
          label="Decisions"
          value={stats.decisions}
          icon={<Scale size={16} />}
        />
        <StatsCard
          label="Threads"
          value={stats.threads}
          icon={<MessageSquare size={16} />}
        />
        <StatsCard
          label="Lineage Edges"
          value={stats.edges}
          icon={<GitFork size={16} />}
        />
        <StatsCard
          label="Pending Flags"
          value={stats.flags}
          icon={<Flag size={16} />}
        />
        <StatsCard
          label="Resonances"
          value={stats.entanglement.resonances}
          icon={<Network size={16} />}
        />
      </div>

      {/* Alerts */}
      {(alerts.stale_decisions > 0 ||
        alerts.conflicts > 0 ||
        alerts.pending_flags > 0 ||
        alerts.stale_threads > 0 ||
        alerts.entanglement_resonances > 0 ||
        alerts.entanglement_loose_ends > 0) && (
        <div className="bg-forge-card border border-forge-border rounded-lg p-4 mb-8">
          <h2 className="text-sm font-semibold text-forge-text mb-3 uppercase tracking-wide">
            Alerts
          </h2>
          <div className="space-y-2 text-sm">
            {alerts.stale_decisions > 0 && (
              <p className="text-tier-medium">
                {alerts.stale_decisions} stale decision
                {alerts.stale_decisions > 1 ? "s" : ""} (3+ hops since validated)
              </p>
            )}
            {alerts.stale_threads > 0 && (
              <p className="text-tier-medium">
                {alerts.stale_threads} stale thread
                {alerts.stale_threads > 1 ? "s" : ""} (3+ hops since validated)
              </p>
            )}
            {alerts.conflicts > 0 && (
              <p className="text-tier-low">
                {alerts.conflicts} decision conflict
                {alerts.conflicts > 1 ? "s" : ""} detected
              </p>
            )}
            {alerts.pending_flags > 0 && (
              <p className="text-cross-project">
                {alerts.pending_flags} pending expedition flag
                {alerts.pending_flags > 1 ? "s" : ""}
              </p>
            )}
            {alerts.entanglement_resonances > 0 && (
              <p className="text-cross-project">
                {alerts.entanglement_resonances} cross-project resonance
                {alerts.entanglement_resonances > 1 ? "s" : ""} detected
              </p>
            )}
            {alerts.entanglement_loose_ends > 0 && (
              <p className="text-tier-medium">
                {alerts.entanglement_loose_ends} entanglement loose end
                {alerts.entanglement_loose_ends > 1 ? "s" : ""} (isolated items)
              </p>
            )}
          </div>
        </div>
      )}

      {/* Projects grid */}
      <div className="mb-4 flex items-center justify-between">
        <h2 className="text-sm font-semibold text-forge-text uppercase tracking-wide">
          Projects
        </h2>
        <span className="text-xs text-forge-muted">
          {projects.length} projects
        </span>
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {projects.map((p) => (
          <ProjectCard key={p.project_uuid} project={p} />
        ))}
      </div>
    </div>
  );
}
