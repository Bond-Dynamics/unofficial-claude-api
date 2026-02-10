import type { ConversationTrace as TraceData } from "@/lib/types";

interface ConversationTraceProps {
  trace: TraceData;
}

interface TraceNode {
  uuid: string;
  project: string;
  compressionTag: string;
  decisionsCarried: string[];
  decisionsDropped: string[];
  threadsCarried: string[];
  threadsResolved: string[];
  isCurrent: boolean;
  isCrossProject: boolean;
}

export function ConversationTrace({ trace }: ConversationTraceProps) {
  const currentUuid = trace.conversation.uuid;

  const nodes: TraceNode[] = [];

  // Root node (from last ancestor's source)
  if (trace.ancestors.length > 0) {
    const first = trace.ancestors[0];
    nodes.push({
      uuid: first.source_conversation,
      project: first.source_project,
      compressionTag: "",
      decisionsCarried: [],
      decisionsDropped: [],
      threadsCarried: [],
      threadsResolved: [],
      isCurrent: first.source_conversation === currentUuid,
      isCrossProject: false,
    });
  }

  // Ancestor chain
  for (const edge of trace.ancestors) {
    nodes.push({
      uuid: edge.target_conversation,
      project: edge.target_project,
      compressionTag: edge.compression_tag,
      decisionsCarried: edge.decisions_carried,
      decisionsDropped: edge.decisions_dropped,
      threadsCarried: edge.threads_carried,
      threadsResolved: edge.threads_resolved,
      isCurrent: edge.target_conversation === currentUuid,
      isCrossProject: edge.source_project !== edge.target_project,
    });
  }

  // If no ancestors, add the current conversation as root
  if (trace.ancestors.length === 0) {
    nodes.push({
      uuid: currentUuid,
      project: trace.conversation.project_name,
      compressionTag: "",
      decisionsCarried: [],
      decisionsDropped: [],
      threadsCarried: [],
      threadsResolved: [],
      isCurrent: true,
      isCrossProject: false,
    });
  }

  // Descendant chain
  for (const edge of trace.descendants) {
    nodes.push({
      uuid: edge.target_conversation,
      project: edge.target_project,
      compressionTag: edge.compression_tag,
      decisionsCarried: edge.decisions_carried,
      decisionsDropped: edge.decisions_dropped,
      threadsCarried: edge.threads_carried,
      threadsResolved: edge.threads_resolved,
      isCurrent: edge.target_conversation === currentUuid,
      isCrossProject: edge.source_project !== edge.target_project,
    });
  }

  return (
    <div className="space-y-0">
      {nodes.map((node, i) => (
        <div key={`${node.uuid}-${i}`}>
          {/* Edge annotation (compression hop) */}
          {node.compressionTag && (
            <div className="flex items-stretch ml-5 gap-3">
              <div className="w-px bg-forge-border" />
              <div className="py-2 text-xs text-forge-muted">
                <span className="font-mono">{node.compressionTag}</span>
                {node.isCrossProject && (
                  <span className="ml-2 text-cross-project font-medium">
                    cross-project
                  </span>
                )}
                <div className="flex gap-3 mt-0.5">
                  {node.decisionsCarried.length > 0 && (
                    <span className="text-tier-high">
                      {node.decisionsCarried.length} carried
                    </span>
                  )}
                  {node.decisionsDropped.length > 0 && (
                    <span className="text-tier-low">
                      {node.decisionsDropped.length} dropped
                    </span>
                  )}
                  {node.threadsCarried.length > 0 && (
                    <span className="text-tier-high">
                      {node.threadsCarried.length} threads
                    </span>
                  )}
                  {node.threadsResolved.length > 0 && (
                    <span className="text-status-resolved">
                      {node.threadsResolved.length} resolved
                    </span>
                  )}
                </div>
              </div>
            </div>
          )}

          {/* Node */}
          <div
            className={`flex items-center gap-3 p-3 rounded-lg border ${
              node.isCurrent
                ? "bg-forge-accent/30 border-tier-high"
                : "bg-forge-card border-forge-border"
            }`}
          >
            <div
              className={`w-2.5 h-2.5 rounded-full shrink-0 ${
                node.isCurrent ? "bg-tier-high" : "bg-forge-muted"
              }`}
            />
            <div className="min-w-0">
              <p className="text-sm text-forge-text font-mono truncate">
                {node.uuid.slice(0, 12)}...
              </p>
              <p className="text-xs text-forge-muted">
                {node.project}
                {i === 0 && trace.ancestors.length > 0 && (
                  <span className="ml-2 text-tier-medium">ROOT</span>
                )}
                {node.isCurrent && (
                  <span className="ml-2 text-tier-high">YOU ARE HERE</span>
                )}
                {i === nodes.length - 1 && !node.isCurrent && (
                  <span className="ml-2 text-forge-muted">LEAF</span>
                )}
              </p>
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}
