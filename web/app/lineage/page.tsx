export const dynamic = "force-dynamic";

import { api } from "@/lib/api";
import { LineageGraphWrapper } from "./LineageGraphWrapper";

export default async function LineagePage() {
  const graphData = await api.getLineageGraph();

  return (
    <div>
      <h1 className="text-xl font-bold text-forge-text mb-2">
        Lineage DAG
      </h1>
      <p className="text-sm text-forge-muted mb-6">
        {graphData.nodes.length} conversations · {graphData.edges.length} edges
        {" · "}Click a node to view its trace
      </p>

      <LineageGraphWrapper data={graphData} />
    </div>
  );
}
