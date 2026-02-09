#!/usr/bin/env python3
"""Forge OS Sync Pipeline — Pre-compression context assembly.

Queries active threads, stale decisions, and conflicts from the
registries and formats them as a structured text block to include
in the compression prompt.

Usage:
    python scripts/prepare_compression.py --project "Forge OS"
    python scripts/prepare_compression.py --project "Forge OS" --no-copy
"""

import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from vectordb.db import get_database
from vectordb.decision_registry import get_active_decisions, get_stale_decisions
from vectordb.expedition_flags import get_pending_flags
from vectordb.thread_registry import get_active_threads, get_stale_threads


def assemble_compression_context(project, db=None):
    """Assemble pre-compression context from registries.

    Args:
        project: Project display name.
        db: Optional database instance.

    Returns:
        Formatted text string for inclusion in compression prompt.
    """
    if db is None:
        db = get_database()

    active_threads = get_active_threads(project, db=db)
    stale_decisions = get_stale_decisions(project, db=db)
    stale_threads = get_stale_threads(project, db=db)
    active_decisions = get_active_decisions(project, db=db)

    # Collect decisions with conflicts
    conflicted = [
        d for d in active_decisions if d.get("conflicts_with")
    ]

    sections = []

    sections.append("## FORGE OS: Pre-Compression Context")
    sections.append(f"**Project:** {project}")
    sections.append("")

    # Active Threads
    sections.append("### Active Threads")
    if active_threads:
        for t in active_threads:
            status_tag = f"[{t['status'].upper()}]"
            priority_tag = f"({t['priority']})" if t.get("priority") else ""
            sections.append(
                f"- {t['local_id']}: {t['title']} {status_tag} {priority_tag}"
            )
            if t.get("blocked_by"):
                sections.append(f"  Blocked by: {', '.join(t['blocked_by'])}")
    else:
        sections.append("- (none)")
    sections.append("")

    # Stale Warnings
    sections.append("### Stale Warnings")
    if stale_decisions or stale_threads:
        for d in stale_decisions:
            hops = d.get("hops_since_validated", 0)
            sections.append(
                f"- DECISION {d['local_id']}: \"{d['text'][:80]}...\" "
                f"({hops} hops since validated)"
            )
        for t in stale_threads:
            hops = t.get("hops_since_validated", 0)
            sections.append(
                f"- THREAD {t['local_id']}: \"{t['title']}\" "
                f"({hops} hops since validated)"
            )
    else:
        sections.append("- (none)")
    sections.append("")

    # Conflict Alerts
    sections.append("### Conflict Alerts")
    if conflicted:
        for d in conflicted:
            conflicts = d.get("conflicts_with", [])
            sections.append(
                f"- {d['local_id']}: \"{d['text'][:80]}...\" "
                f"conflicts with {len(conflicts)} decision(s): "
                f"{', '.join(c[:8] + '...' for c in conflicts)}"
            )
    else:
        sections.append("- (none)")
    sections.append("")

    # Pending Expedition Flags
    pending_flags = get_pending_flags(project, db=db)
    sections.append("### Pending Expedition Flags")
    if pending_flags:
        sections.append(
            f"- WARNING: {len(pending_flags)} uncompiled flag(s). "
            "Run \"compile expedition\" or \"compile flagged\" before "
            "compressing to avoid losing flagged findings."
        )
        for f in pending_flags[:10]:
            cat = f.get("category", "general")
            conv = f.get("conversation_id", "?")[:8]
            sections.append(
                f"- [{cat}] \"{f['description'][:80]}\" (from {conv}...)"
            )
        if len(pending_flags) > 10:
            sections.append(f"- ...and {len(pending_flags) - 10} more")
    else:
        sections.append("- (none)")
    sections.append("")

    # Decision count summary
    sections.append(
        f"**Summary:** {len(active_decisions)} active decisions, "
        f"{len(active_threads)} active threads, "
        f"{len(stale_decisions)} stale decisions, "
        f"{len(stale_threads)} stale threads, "
        f"{len(conflicted)} conflicts, "
        f"{len(pending_flags)} pending flags"
    )

    return "\n".join(sections)


def _copy_to_clipboard(text):
    """Copy text to macOS clipboard via pbcopy."""
    try:
        subprocess.run(
            ["pbcopy"], input=text, text=True, check=True,
        )
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Assemble pre-compression context from Forge OS registries"
    )
    parser.add_argument("--project", required=True, help="Project display name")
    parser.add_argument("--no-copy", action="store_true", help="Don't copy to clipboard")

    args = parser.parse_args()

    context = assemble_compression_context(args.project)
    print(context)

    if not args.no_copy:
        if _copy_to_clipboard(context):
            print("\n[Copied to clipboard]")
        else:
            print("\n[Could not copy to clipboard]")


if __name__ == "__main__":
    main()
