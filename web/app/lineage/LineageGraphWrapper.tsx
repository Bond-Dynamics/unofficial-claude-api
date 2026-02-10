"use client";

import { useState, useEffect, useRef } from "react";
import { LineageGraph } from "@/components/LineageGraph";
import type { GraphData } from "@/lib/types";

interface Props {
  data: GraphData;
}

export function LineageGraphWrapper({ data }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [dimensions, setDimensions] = useState({ width: 900, height: 600 });

  useEffect(() => {
    function updateSize() {
      if (containerRef.current) {
        const rect = containerRef.current.getBoundingClientRect();
        setDimensions({
          width: Math.max(rect.width, 400),
          height: Math.max(window.innerHeight - 250, 400),
        });
      }
    }
    updateSize();
    window.addEventListener("resize", updateSize);
    return () => window.removeEventListener("resize", updateSize);
  }, []);

  return (
    <div ref={containerRef}>
      <LineageGraph
        data={data}
        width={dimensions.width}
        height={dimensions.height}
      />
    </div>
  );
}
