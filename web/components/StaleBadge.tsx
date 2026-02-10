interface StaleBadgeProps {
  hops: number;
  threshold?: number;
}

export function StaleBadge({ hops, threshold = 3 }: StaleBadgeProps) {
  if (hops < threshold) return null;

  const color =
    hops >= threshold * 2
      ? "bg-tier-low/20 text-tier-low"
      : "bg-tier-medium/20 text-tier-medium";

  return (
    <span
      className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-mono ${color}`}
      title={`${hops} hops since last validated (threshold: ${threshold})`}
    >
      {hops} hops
    </span>
  );
}
