"use client";

import { useRouter } from "next/navigation";
import { useMemo } from "react";
import dynamic from "next/dynamic";
import type { GraphData } from "@/lib/types";

// eslint-disable-next-line @typescript-eslint/no-explicit-any
const ForceGraph2D = dynamic(() => import("react-force-graph-2d") as any, {
  ssr: false,
// eslint-disable-next-line @typescript-eslint/no-explicit-any
}) as any;

const PROJECT_COLORS = [
  "#4ade80", "#60a5fa", "#f472b6", "#fbbf24", "#a78bfa",
  "#34d399", "#fb923c", "#e879f9", "#2dd4bf", "#f87171",
  "#818cf8", "#a3e635", "#22d3ee", "#c084fc", "#fb7185",
];

interface LineageGraphProps {
  data: GraphData;
  width?: number;
  height?: number;
}

export function LineageGraph({ data, width = 900, height = 600 }: LineageGraphProps) {
  const router = useRouter();

  const projectColorMap = useMemo(() => {
    const projects = [...new Set(data.nodes.map((n) => n.project))].sort();
    const map: Record<string, string> = {};
    projects.forEach((p, i) => {
      map[p] = PROJECT_COLORS[i % PROJECT_COLORS.length];
    });
    return map;
  }, [data.nodes]);

  const graphData = useMemo(
    () => ({
      nodes: data.nodes.map((n) => ({ ...n })),
      links: data.edges.map((e) => ({
        ...e,
        source: e.source,
        target: e.target,
      })),
    }),
    [data]
  );

  return (
    <div>
      <div className="flex flex-wrap gap-3 mb-4">
        {Object.entries(projectColorMap).map(([name, color]) => (
          <span key={name} className="flex items-center gap-1.5 text-xs text-forge-muted">
            <span
              className="w-2.5 h-2.5 rounded-full inline-block"
              style={{ backgroundColor: color }}
            />
            {name || "(no project)"}
          </span>
        ))}
      </div>

      <div className="bg-forge-card border border-forge-border rounded-lg overflow-hidden">
        <ForceGraph2D
          graphData={graphData}
          width={width}
          height={height}
          nodeLabel="name"
          nodeColor={(node: Record<string, unknown>) =>
            projectColorMap[(node.project as string) ?? ""] ?? "#6b7280"
          }
          nodeRelSize={5}
          linkColor={(link: Record<string, unknown>) =>
            link.cross_project ? "#a78bfa" : "#374151"
          }
          linkLineDash={(link: Record<string, unknown>) =>
            link.cross_project ? [5, 5] : []
          }
          linkDirectionalArrowLength={4}
          linkDirectionalArrowRelPos={1}
          onNodeClick={(node: Record<string, unknown>) => {
            if (node.id) {
              router.push(`/lineage/${node.id}`);
            }
          }}
          backgroundColor="#16213e"
          nodeCanvasObjectMode={() => "after"}
          nodeCanvasObject={(
            node: Record<string, unknown>,
            ctx: CanvasRenderingContext2D,
          ) => {
            const x = node.x as number | undefined;
            const y = node.y as number | undefined;
            if (x === undefined || y === undefined) return;
            const label = ((node.name as string) ?? "").slice(0, 18);
            ctx.font = "3px sans-serif";
            ctx.textAlign = "center";
            ctx.fillStyle = "#8892b0";
            ctx.fillText(label, x, y + 7);
          }}
        />
      </div>
    </div>
  );
}
