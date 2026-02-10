export const dynamic = "force-dynamic";

import Link from "next/link";
import { ArrowLeft } from "lucide-react";
import { api } from "@/lib/api";
import { DecisionTable } from "@/components/DecisionTable";
import { ThreadTable } from "@/components/ThreadTable";
import type {
  Compression,
  Conversation,
  Decision,
  ExpeditionFlag,
  PrimingBlock,
  Thread,
} from "@/lib/types";

interface PageProps {
  params: Promise<{ name: string }>;
}

export default async function ProjectDetail({ params }: PageProps) {
  const { name } = await params;
  const projectName = decodeURIComponent(name);

  const [conversations, decisions, threads, compressions, priming, flags] =
    await Promise.all([
      api.getProjectConversations(projectName),
      api.getProjectDecisions(projectName),
      api.getProjectThreads(projectName),
      api.getProjectCompressions(projectName),
      api.getProjectPriming(projectName),
      api.getProjectFlags(projectName),
    ]);

  return (
    <div>
      <Link
        href="/"
        className="inline-flex items-center gap-1.5 text-sm text-forge-muted hover:text-forge-text mb-4"
      >
        <ArrowLeft size={14} />
        Back to Overview
      </Link>

      <h1 className="text-xl font-bold text-forge-text mb-1">{projectName}</h1>
      <p className="text-sm text-forge-muted mb-6">
        {conversations.length} conversations · {decisions.length} decisions ·{" "}
        {threads.length} threads
      </p>

      {/* Conversations */}
      <Section title="Conversations" count={conversations.length}>
        <ConversationList conversations={conversations} />
      </Section>

      {/* Decisions */}
      <Section title="Decisions" count={decisions.length}>
        <DecisionTable decisions={decisions} />
      </Section>

      {/* Threads */}
      <Section title="Threads" count={threads.length}>
        <ThreadTable threads={threads} />
      </Section>

      {/* Compressions */}
      <Section title="Compressions" count={compressions.length}>
        <CompressionTimeline compressions={compressions} />
      </Section>

      {/* Priming Blocks */}
      <Section title="Priming Blocks" count={priming.length}>
        <PrimingList blocks={priming} />
      </Section>

      {/* Expedition Flags */}
      <Section title="Expedition Flags" count={flags.length}>
        <FlagList flags={flags} />
      </Section>
    </div>
  );
}

function Section({
  title,
  count,
  children,
}: {
  title: string;
  count: number;
  children: React.ReactNode;
}) {
  return (
    <div className="mb-8">
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-sm font-semibold text-forge-text uppercase tracking-wide">
          {title}
        </h2>
        <span className="text-xs text-forge-muted">{count}</span>
      </div>
      <div className="bg-forge-card border border-forge-border rounded-lg p-4">
        {children}
      </div>
    </div>
  );
}

function ConversationList({ conversations }: { conversations: Conversation[] }) {
  if (conversations.length === 0) {
    return <p className="text-sm text-forge-muted">No conversations.</p>;
  }

  return (
    <div className="space-y-2">
      {conversations.map((c) => (
        <div
          key={c.uuid}
          className="flex items-center justify-between py-2 border-b border-forge-border/50 last:border-0"
        >
          <div className="min-w-0">
            <p className="text-sm text-forge-text truncate">
              {c.conversation_name}
            </p>
            <p className="text-xs text-forge-muted font-mono">
              {c.uuid.slice(0, 12)}...
            </p>
          </div>
          <div className="text-xs text-forge-muted whitespace-nowrap ml-4">
            {c.created_at ? new Date(c.created_at).toLocaleDateString() : "—"}
          </div>
        </div>
      ))}
    </div>
  );
}

function CompressionTimeline({ compressions }: { compressions: Compression[] }) {
  if (compressions.length === 0) {
    return <p className="text-sm text-forge-muted">No compression events.</p>;
  }

  return (
    <div className="space-y-3">
      {compressions.map((c) => (
        <div
          key={c.compression_tag}
          className="border-b border-forge-border/50 pb-3 last:border-0 last:pb-0"
        >
          <p className="text-sm font-mono text-forge-text">
            {c.compression_tag}
          </p>
          <div className="flex gap-4 mt-1 text-xs text-forge-muted">
            <span>{c.decisions_captured.length} decisions</span>
            <span>{c.threads_captured.length} threads</span>
            <span>{c.artifacts_captured.length} artifacts</span>
            <span>
              {c.created_at
                ? new Date(c.created_at).toLocaleDateString()
                : "—"}
            </span>
          </div>
        </div>
      ))}
    </div>
  );
}

function PrimingList({ blocks }: { blocks: PrimingBlock[] }) {
  if (blocks.length === 0) {
    return <p className="text-sm text-forge-muted">No priming blocks.</p>;
  }

  return (
    <div className="space-y-3">
      {blocks.map((b) => (
        <div
          key={b.uuid}
          className="border-b border-forge-border/50 pb-3 last:border-0 last:pb-0"
        >
          <p className="text-sm font-semibold text-forge-text">
            {b.territory_name}
          </p>
          <p className="text-xs text-forge-muted mt-1">
            Keys: {b.territory_keys_text}
          </p>
          <p className="text-xs text-forge-muted">
            Floor: {b.confidence_floor} · Expeditions:{" "}
            {b.source_expeditions.join(", ") || "—"}
          </p>
        </div>
      ))}
    </div>
  );
}

function FlagList({ flags }: { flags: ExpeditionFlag[] }) {
  if (flags.length === 0) {
    return <p className="text-sm text-forge-muted">No expedition flags.</p>;
  }

  const CATEGORY_COLORS: Record<string, string> = {
    inversion: "text-cross-project",
    isomorphism: "text-tier-high",
    fsd: "text-tier-medium",
    manifestation: "text-tier-high",
    trap: "text-tier-low",
    general: "text-forge-muted",
  };

  return (
    <div className="space-y-2">
      {flags.map((f) => (
        <div
          key={f.uuid}
          className="flex items-start gap-3 py-2 border-b border-forge-border/50 last:border-0"
        >
          <span
            className={`text-xs font-mono whitespace-nowrap ${
              CATEGORY_COLORS[f.category] ?? "text-forge-muted"
            }`}
          >
            [{f.category}]
          </span>
          <p className="text-sm text-forge-text line-clamp-2">
            {f.description}
          </p>
        </div>
      ))}
    </div>
  );
}
