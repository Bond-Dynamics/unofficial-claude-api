#!/usr/bin/env python3
"""Forge OS Expedition Flags — Show pending flags for compilation.

Usage:
    python scripts/show_flags.py --project "Forge OS"
    python scripts/show_flags.py --project "Forge OS" --category inversion
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from vectordb.expedition_flags import get_flags_by_category, get_pending_flags


def format_flags(flags):
    """Format flags grouped by category."""
    if not flags:
        return "No pending flags."

    by_category = {}
    for f in flags:
        cat = f.get("category", "general")
        by_category.setdefault(cat, []).append(f)

    lines = [f"Pending expedition flags: {len(flags)} total\n"]

    for cat in sorted(by_category.keys()):
        lines.append(f"[{cat.upper()}]")
        for f in by_category[cat]:
            conv = f.get("conversation_id", "?")[:8]
            ts = f.get("created_at", "?")[:10]
            lines.append(f"  - {f['description'][:120]}")
            lines.append(f"    from: {conv}...  flagged: {ts}")
            if f.get("context"):
                lines.append(f"    context: {f['context'][:100]}...")
        lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Show pending expedition flags"
    )
    parser.add_argument("--project", required=True, help="Project display name")
    parser.add_argument("--category", help="Filter by category")

    args = parser.parse_args()

    if args.category:
        flags = get_flags_by_category(args.project, args.category)
    else:
        flags = get_pending_flags(args.project)

    print(format_flags(flags))


if __name__ == "__main__":
    main()
