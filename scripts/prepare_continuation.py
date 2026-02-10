#!/usr/bin/env python3
"""Forge OS Sync Pipeline — Pre-continuation context assembly.

Queries active decisions (grouped by tier), active threads, stale items,
and lineage to produce a continuation-ready context block for pasting
into a new conversation.

Usage:
    python scripts/prepare_continuation.py --project "Forge OS"
    python scripts/prepare_continuation.py --project "Forge OS" --no-copy
"""

import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from vectordb.db import get_database
from vectordb.decision_registry import get_active_decisions, get_stale_decisions
from vectordb.expedition_flags import get_pending_flags
from vectordb.lineage import get_ancestors
from vectordb.priming_registry import find_relevant_priming, list_priming_blocks
from vectordb.thread_registry import get_active_threads, get_stale_threads


def _truncate_words(text, max_words=400):
    """Truncate text to max_words, appending '...' if truncated."""
    words = text.split()
    if len(words) <= max_words:
        return text
    return " ".join(words[:max_words]) + "..."


def assemble_continuation_context(
    project, conversation_id=None, lineage_depth=3, topic=None, db=None,
):
    """Assemble continuation context from registries.

    Args:
        project: Project display name.
        conversation_id: Optional current conversation UUID for lineage.
        lineage_depth: How many ancestor hops to include.
        topic: Optional topic text for semantic priming block activation.
        db: Optional database instance.

    Returns:
        Formatted text string for pasting into new conversation.
    """
    if db is None:
        db = get_database()

    active_decisions = get_active_decisions(project, db=db)
    active_threads = get_active_threads(project, db=db)
    stale_decisions = get_stale_decisions(project, db=db)
    stale_threads = get_stale_threads(project, db=db)

    lineage = []
    if conversation_id:
        lineage = get_ancestors(conversation_id, depth=lineage_depth, db=db)

    # Priming blocks — project-level + optional semantic match
    priming_blocks = list_priming_blocks(project, db=db)
    if topic:
        semantic_matches = find_relevant_priming(topic, project=project, db=db)
        seen_uuids = {b["uuid"] for b in priming_blocks}
        for match in semantic_matches:
            if match["uuid"] not in seen_uuids:
                priming_blocks.append(match)
    priming_blocks = priming_blocks[:3]

    pending_flags = get_pending_flags(project, db=db)

    sections = []

    sections.append("## FORGE OS: Continuation Context")
    sections.append(f"**Project:** {project}")
    sections.append("")

    # Decisions In Force (grouped by tier)
    sections.append("### Decisions In Force")
    if active_decisions:
        tier_groups = {}
        for d in active_decisions:
            tier = d.get("epistemic_tier")
            tier_label = f"Tier {tier}" if tier is not None else "Untiered"
            tier_groups.setdefault(tier_label, []).append(d)

        for tier_label in sorted(tier_groups.keys(), reverse=True):
            sections.append(f"\n**{tier_label}:**")
            for d in tier_groups[tier_label]:
                label = d.get("global_display_id") or d["local_id"]
                text_preview = d.get("text", d.get("title", ""))[:120]
                deps = d.get("dependencies", [])
                dep_str = f" [deps: {', '.join(deps)}]" if deps else ""
                conflicts = d.get("conflicts_with", [])
                conflict_str = f" [CONFLICTS: {len(conflicts)}]" if conflicts else ""
                sections.append(
                    f"- {label}: {text_preview}{dep_str}{conflict_str}"
                )
    else:
        sections.append("- (none)")
    sections.append("")

    # Open Threads
    sections.append("### Open Threads")
    if active_threads:
        for t in active_threads:
            label = t.get("global_display_id") or t["local_id"]
            status_tag = f"[{t['status'].upper()}]"
            priority_tag = f"({t['priority']})" if t.get("priority") else ""
            hops = t.get("hops_since_validated", 0)
            hops_str = f" [{hops} hops]" if hops > 0 else ""
            sections.append(
                f"- {label}: {t['title']} {status_tag} "
                f"{priority_tag}{hops_str}"
            )
            if t.get("blocked_by"):
                sections.append(f"  Blocked by: {', '.join(t['blocked_by'])}")
    else:
        sections.append("- (none)")
    sections.append("")

    # Warnings
    has_warnings = stale_decisions or stale_threads
    sections.append("### Warnings")
    if has_warnings:
        for d in stale_decisions:
            label = d.get("global_display_id") or d["local_id"]
            hops = d.get("hops_since_validated", 0)
            sections.append(
                f"- STALE DECISION {label}: "
                f"\"{d['text'][:60]}...\" ({hops} hops)"
            )
        for t in stale_threads:
            label = t.get("global_display_id") or t["local_id"]
            hops = t.get("hops_since_validated", 0)
            sections.append(
                f"- STALE THREAD {label}: "
                f"\"{t['title']}\" ({hops} hops)"
            )
    else:
        sections.append("- (none)")
    sections.append("")

    # Lineage
    sections.append("### Lineage")
    if lineage:
        for i, edge in enumerate(lineage):
            src = edge.get("source_conversation", "?")[:8]
            tgt = edge.get("target_conversation", "?")[:8]
            tag = edge.get("compression_tag", "")
            carried = len(edge.get("decisions_carried", []))
            dropped = len(edge.get("decisions_dropped", []))
            sections.append(
                f"- Hop {i + 1}: {src}... -> {tgt}... "
                f"(tag: {tag}, {carried} decisions carried, "
                f"{dropped} dropped)"
            )
    else:
        sections.append("- (no lineage recorded)")
    sections.append("")

    # Priming Blocks
    sections.append("### Priming Blocks")
    if priming_blocks:
        for block in priming_blocks:
            sections.append(f"\n#### PRIMING: {block.get('territory_name', 'Unknown')}")
            keys = block.get("territory_keys_text", ", ".join(block.get("territory_keys", [])))
            sections.append(f"**Territory Keys:** {keys}")
            sections.append(f"**Confidence Floor:** {block.get('confidence_floor', 0.3)}")
            exps = block.get("source_expeditions", [])
            if exps:
                sections.append(f"**Source:** {', '.join(exps)}")
            sections.append("")
            sections.append(_truncate_words(block.get("content", "")))
            sections.append("")
    else:
        sections.append("- (no priming blocks for this project)")
    sections.append("")

    # Pending Expedition Flags
    sections.append("### Pending Expedition Flags")
    display_flags = pending_flags[:10]
    if display_flags:
        remaining = len(pending_flags) - len(display_flags)
        sections.append(f"({len(pending_flags)} uncompiled)")
        by_category = {}
        for f in display_flags:
            cat = f.get("category", "general")
            by_category.setdefault(cat, []).append(f)

        for cat in sorted(by_category.keys()):
            sections.append(f"\n**{cat.title()}:**")
            for f in by_category[cat]:
                conv = f.get("conversation_id", "?")[:8]
                sections.append(f"- \"{f['description'][:100]}\" (from {conv}...)")

        if remaining > 0:
            sections.append(f"\n*...and {remaining} more*")
    else:
        sections.append("- (none)")
    sections.append("")

    # Summary
    sections.append(
        f"**Summary:** {len(active_decisions)} decisions in force, "
        f"{len(active_threads)} open threads, "
        f"{len(stale_decisions) + len(stale_threads)} stale items, "
        f"{len(lineage)} lineage hops, "
        f"{len(priming_blocks)} priming blocks, "
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
        description="Assemble continuation context from Forge OS registries"
    )
    parser.add_argument("--project", required=True, help="Project display name")
    parser.add_argument("--conversation-id", help="Current conversation UUID for lineage")
    parser.add_argument("--lineage-depth", type=int, default=3, help="Lineage hops to show")
    parser.add_argument("--topic", help="Topic text for semantic priming block activation")
    parser.add_argument("--no-copy", action="store_true", help="Don't copy to clipboard")

    args = parser.parse_args()

    context = assemble_continuation_context(
        args.project,
        conversation_id=args.conversation_id,
        lineage_depth=args.lineage_depth,
        topic=args.topic,
    )
    print(context)

    if not args.no_copy:
        if _copy_to_clipboard(context):
            print("\n[Copied to clipboard]")
        else:
            print("\n[Could not copy to clipboard]")


if __name__ == "__main__":
    main()
