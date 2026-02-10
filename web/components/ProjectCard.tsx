import Link from "next/link";
import type { Project } from "@/lib/types";

interface ProjectCardProps {
  project: Project;
}

export function ProjectCard({ project }: ProjectCardProps) {
  return (
    <Link
      href={`/projects/${encodeURIComponent(project.project_name)}`}
      className="block bg-forge-card border border-forge-border rounded-lg p-4 hover:border-forge-accent transition-colors"
    >
      <h3 className="text-sm font-semibold text-forge-text truncate">
        {project.project_name}
      </h3>
      <div className="mt-3 flex items-center gap-4 text-xs text-forge-muted">
        <span>
          <strong className="text-forge-text">{project.conversation_count}</strong>{" "}
          convos
        </span>
        {project.decision_count !== undefined && (
          <span>
            <strong className="text-forge-text">{project.decision_count}</strong>{" "}
            decisions
          </span>
        )}
        {project.thread_count !== undefined && (
          <span>
            <strong className="text-forge-text">{project.thread_count}</strong>{" "}
            threads
          </span>
        )}
        {(project.flag_count ?? 0) > 0 && (
          <span className="text-tier-medium">
            {project.flag_count} flags
          </span>
        )}
      </div>
    </Link>
  );
}
