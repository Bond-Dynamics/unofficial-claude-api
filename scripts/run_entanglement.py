#!/usr/bin/env python3
"""CLI entry point for cross-project entanglement discovery.

Usage:
    python scripts/run_entanglement.py                        # full scan
    python scripts/run_entanglement.py --project "Wavelength" # one project
    python scripts/run_entanglement.py --json                 # JSON output
    python scripts/run_entanglement.py --min-similarity 0.65  # override threshold
"""

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from vectordb.entanglement import scan, scan_project


def _print_human(result):
    """Print a human-readable summary of an entanglement scan."""
    print(f"\n=== Entanglement Scan ===")
    if result.get("project"):
        print(f"Project: {result['project']}")
    print(f"Scanned at: {result['scanned_at']}")
    print(f"Decisions scanned: {result['decisions_scanned']}")
    print(f"Threads scanned: {result['threads_scanned']}")
    if result["threads_embedded"] > 0:
        print(f"Threads backfill-embedded: {result['threads_embedded']}")
    print(f"Resonances found: {result['resonances_found']}")
    print(f"  Strong (>= 0.65): {result['by_tier']['strong']}")
    print(f"  Weak   (>= 0.50): {result['by_tier']['weak']}")
    print()

    clusters = result.get("clusters", [])
    if clusters:
        print(f"--- {len(clusters)} Entanglement Cluster(s) ---\n")
        for c in clusters:
            projects_str = ", ".join(c["projects"])
            print(f"Cluster {c['cluster_id']} ({len(c['items'])} items, "
                  f"avg similarity: {c['avg_similarity']:.2f})")
            print(f"  Projects: {projects_str}")
            for item in c["items"]:
                label = item["local_id"] or item["uuid"][:12]
                print(f"  - [{item['type'].upper()}] {label}: {item['text'][:80]}")
            strongest = c["strongest_link"]
            print(f"  Strongest link: {strongest['similarity']:.2f}")
            print()
    else:
        print("No entanglement clusters found.\n")

    bridges = result.get("bridges", [])
    if bridges:
        print(f"--- {len(bridges)} Lineage Bridge(s) ---\n")
        for b in bridges:
            projects_str = ", ".join(b["projects"])
            print(f"  [{b['type'].upper()}] {b['uuid'][:12]}... "
                  f"spans {projects_str} ({b['edge_count']} edges)")
        print()

    loose_ends = result.get("loose_ends", [])
    if loose_ends:
        print(f"--- {len(loose_ends)} Loose End(s) ---\n")
        for le in loose_ends:
            label = le["local_id"] or le["uuid"][:12]
            print(f"  [{le['type'].upper()}] {label} ({le['project']}): {le['text'][:60]}")
        print()


def main():
    parser = argparse.ArgumentParser(
        description="Cross-project entanglement discovery scanner"
    )
    parser.add_argument(
        "--project", "-p",
        help="Scan centered on a specific project",
    )
    parser.add_argument(
        "--json", "-j",
        action="store_true",
        dest="json_output",
        help="Output raw JSON instead of human-readable summary",
    )
    parser.add_argument(
        "--min-similarity", "-s",
        type=float,
        default=None,
        help="Override minimum similarity threshold (default: 0.50)",
    )

    args = parser.parse_args()

    if args.project:
        result = scan_project(args.project, min_similarity=args.min_similarity)
    else:
        result = scan(min_similarity=args.min_similarity)

    if args.json_output:
        print(json.dumps(result, indent=2, default=str))
    else:
        _print_human(result)


if __name__ == "__main__":
    main()
