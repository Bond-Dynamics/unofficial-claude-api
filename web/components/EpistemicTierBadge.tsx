interface EpistemicTierBadgeProps {
  tier: number | null;
}

export function EpistemicTierBadge({ tier }: EpistemicTierBadgeProps) {
  if (tier === null || tier === undefined) {
    return (
      <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-mono bg-gray-800 text-gray-400">
        --
      </span>
    );
  }

  const color =
    tier >= 0.8
      ? "bg-tier-high/20 text-tier-high"
      : tier >= 0.3
        ? "bg-tier-medium/20 text-tier-medium"
        : "bg-tier-low/20 text-tier-low";

  return (
    <span
      className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-mono ${color}`}
      title={`Epistemic tier: ${tier}`}
    >
      {tier.toFixed(2)}
    </span>
  );
}
