interface ConflictBadgeProps {
  count: number;
}

export function ConflictBadge({ count }: ConflictBadgeProps) {
  if (count === 0) return null;

  return (
    <span
      className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium bg-tier-low/20 text-tier-low"
      title={`${count} conflict${count > 1 ? "s" : ""} detected`}
    >
      {count} conflict{count > 1 ? "s" : ""}
    </span>
  );
}
