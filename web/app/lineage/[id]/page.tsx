export const dynamic = "force-dynamic";

import Link from "next/link";
import { ArrowLeft } from "lucide-react";
import { api } from "@/lib/api";
import { ConversationTrace } from "@/components/ConversationTrace";

interface PageProps {
  params: Promise<{ id: string }>;
}

export default async function ConversationTracePage({ params }: PageProps) {
  const { id } = await params;

  let trace;
  try {
    trace = await api.getConversationTrace(id);
  } catch {
    return (
      <div>
        <Link
          href="/lineage"
          className="inline-flex items-center gap-1.5 text-sm text-forge-muted hover:text-forge-text mb-4"
        >
          <ArrowLeft size={14} />
          Back to Lineage
        </Link>
        <p className="text-sm text-tier-low">
          Conversation not found: {id}
        </p>
      </div>
    );
  }

  const conv = trace.conversation;

  return (
    <div>
      <Link
        href="/lineage"
        className="inline-flex items-center gap-1.5 text-sm text-forge-muted hover:text-forge-text mb-4"
      >
        <ArrowLeft size={14} />
        Back to Lineage
      </Link>

      {/* Conversation header */}
      <div className="bg-forge-card border border-forge-border rounded-lg p-4 mb-6">
        <h1 className="text-lg font-bold text-forge-text">
          {conv.conversation_name}
        </h1>
        <div className="flex flex-wrap gap-4 mt-2 text-xs text-forge-muted">
          <span>
            Project:{" "}
            <Link
              href={`/projects/${encodeURIComponent(conv.project_name)}`}
              className="text-cross-project hover:underline"
            >
              {conv.project_name}
            </Link>
          </span>
          <span>
            Created:{" "}
            {conv.created_at
              ? new Date(conv.created_at).toLocaleDateString()
              : "—"}
          </span>
          <span className="font-mono">UUID: {conv.uuid}</span>
        </div>
        {trace.cross_project && (
          <p className="mt-2 text-xs text-cross-project">
            This lineage chain spans multiple projects:{" "}
            {trace.projects.join(", ")}
          </p>
        )}
      </div>

      {/* Chain stats */}
      <div className="flex gap-4 mb-4 text-xs text-forge-muted">
        <span>{trace.ancestors.length} ancestor hops</span>
        <span>{trace.descendants.length} descendant hops</span>
        <span>{trace.conversations.length} total conversations in chain</span>
      </div>

      {/* Lineage chain */}
      <h2 className="text-sm font-semibold text-forge-text uppercase tracking-wide mb-3">
        Lineage Chain
      </h2>
      <ConversationTrace trace={trace} />
    </div>
  );
}
