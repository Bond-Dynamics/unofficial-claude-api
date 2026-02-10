#!/usr/bin/env python3
"""Forge OS — Trace conversation lineage across projects.

Renders the lineage graph as an ASCII tree showing how conversations
traverse across compression hops and between projects.

Usage:
    # Trace a specific conversation (by source ID, UUID, or name fragment)
    python scripts/trace_lineage.py bc76c40c

    # Show full graph
    python scripts/trace_lineage.py --full-graph

    # Filter by project
    python scripts/trace_lineage.py --project "Attention Framework"

    # List all registered projects
    python scripts/trace_lineage.py --list-projects

    # JSON output
    python scripts/trace_lineage.py bc76c40c --json
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from vectordb.conversation_registry import (
    get_conversation,
    list_project_conversations,
    list_projects,
    resolve_id,
)
from vectordb.db import get_database
from vectordb.lineage import (
    get_full_graph,
    trace_conversation,
)


def _short_id(uuid_str):
    """First 8 chars of a UUID for display."""
    return uuid_str[:8] if uuid_str else "????????"


def _lookup_name(source_id, db):
    """Look up a conversation's display name from the registry."""
    doc = get_conversation(source_id, db=db)
    if doc:
        return doc.get("conversation_name", source_id)
    return source_id


def _format_edge_detail(edge):
    """Format decision/thread counts for an edge."""
    carried = len(edge.get("decisions_carried", []))
    dropped = len(edge.get("decisions_dropped", []))
    threads_c = len(edge.get("threads_carried", []))
    threads_r = len(edge.get("threads_resolved", []))

    parts = []
    if carried:
        parts.append(f"{carried} decisions carried")
    if dropped:
        parts.append(f"{dropped} dropped")
    if threads_c:
        parts.append(f"{threads_c} threads carried")
    if threads_r:
        parts.append(f"{threads_r} resolved")

    return ", ".join(parts) if parts else "no payload"


def _format_project_label(project_name):
    """Format a project name for display."""
    if not project_name:
        return ""
    return f" ({project_name})"


def render_trace(conversation_id, db):
    """Render a conversation's lineage trace as ASCII tree."""
    trace = trace_conversation(conversation_id, db=db)

    if not trace["ancestors"] and not trace["descendants"]:
        name = _lookup_name(conversation_id, db)
        print(f"[{_short_id(conversation_id)}] {name}")
        print("  (no lineage edges — this is a standalone conversation)")
        return trace

    if trace["cross_project"]:
        projects_str = ", ".join(sorted(trace["projects"]))
        print(f"Cross-project lineage spanning: {projects_str}")
        print()

    # Build ordered chain: ancestors (root→target) + self + descendants
    chain_edges = trace["ancestors"] + trace["descendants"]

    if chain_edges:
        first_edge = chain_edges[0]
        first_src = first_edge["source_conversation"]
        first_name = _lookup_name(first_src, db)
        first_project = first_edge.get("source_project", "")
        print(f"[{_short_id(first_src)}] {first_name}{_format_project_label(first_project)}")

    for edge in chain_edges:
        tag = edge.get("compression_tag", "")
        detail = _format_edge_detail(edge)
        target = edge["target_conversation"]
        target_name = _lookup_name(target, db)
        target_project = edge.get("target_project", "")

        tag_line = f"tag: {tag}" if tag else "no tag"
        print(f"    |")
        print(f"    | compressed via: {tag_line}")
        print(f"    | {detail}")
        print(f"    v")
        print(f"[{_short_id(target)}] {target_name}{_format_project_label(target_project)}")

    print()
    print(f"Total: {len(trace['conversations'])} conversations, "
          f"{len(chain_edges)} compression hops")

    return trace


def render_full_graph(project=None, db=None):
    """Render the full lineage graph."""
    if db is None:
        db = get_database()

    edges = get_full_graph(project=project, db=db)

    if not edges:
        label = f" for project '{project}'" if project else ""
        print(f"No lineage edges found{label}.")
        return

    # Collect all conversations and projects
    conversations = set()
    projects = set()
    for edge in edges:
        conversations.add(edge["source_conversation"])
        conversations.add(edge["target_conversation"])
        if edge.get("source_project"):
            projects.add(edge["source_project"])
        if edge.get("target_project"):
            projects.add(edge["target_project"])

    projects.discard("")

    print(f"Full Lineage Graph ({len(edges)} edges, "
          f"{len(conversations)} conversations)")
    if projects:
        print(f"Projects: {', '.join(sorted(projects))}")
    print()

    # Find roots (conversations that are sources but never targets)
    targets = {e["target_conversation"] for e in edges}
    sources = {e["source_conversation"] for e in edges}
    roots = sources - targets

    # Render from each root
    visited = set()
    for root in sorted(roots):
        _render_subtree(root, edges, db, visited, indent=0)

    # Handle any orphan edges (cycles or disconnected)
    remaining = [e for e in edges
                 if e["source_conversation"] not in visited]
    for edge in remaining:
        if edge["source_conversation"] not in visited:
            _render_subtree(
                edge["source_conversation"], edges, db, visited, indent=0,
            )


def _render_subtree(conv_id, all_edges, db, visited, indent):
    """Recursively render a conversation and its descendants."""
    if conv_id in visited:
        prefix = "  " * indent
        print(f"{prefix}[{_short_id(conv_id)}] (already shown)")
        return

    visited.add(conv_id)
    prefix = "  " * indent
    name = _lookup_name(conv_id, db)
    print(f"{prefix}[{_short_id(conv_id)}] {name}")

    children = [e for e in all_edges if e["source_conversation"] == conv_id]
    for edge in children:
        tag = edge.get("compression_tag", "")
        detail = _format_edge_detail(edge)
        target_project = edge.get("target_project", "")
        child_prefix = "  " * (indent + 1)

        tag_display = tag if tag else "no tag"
        project_label = _format_project_label(target_project)

        print(f"{child_prefix}|-- {tag_display} [{detail}]{project_label}")
        _render_subtree(
            edge["target_conversation"], all_edges, db, visited, indent + 2,
        )


def render_projects(db):
    """List all registered projects with counts."""
    projects = list_projects(db=db)

    if not projects:
        print("No projects registered. Run register_conversations.py first.")
        return

    print(f"Registered Projects ({len(projects)} total)")
    print("-" * 60)

    for p in projects:
        earliest = ""
        if p.get("earliest_at"):
            dt = datetime.fromtimestamp(p["earliest_at"] / 1000, tz=timezone.utc)
            earliest = dt.strftime("%Y-%m-%d")

        print(f"  {p['project_name']}")
        print(f"    Conversations: {p['conversation_count']}")
        print(f"    UUID: {p['project_uuid'][:16]}...")
        if earliest:
            print(f"    Since: {earliest}")
        print()


def render_project_conversations(project_name, db):
    """List all conversations for a specific project."""
    convos = list_project_conversations(project_name, db=db)

    if not convos:
        print(f"No conversations found for project '{project_name}'.")
        return

    print(f"Conversations in '{project_name}' ({len(convos)} total)")
    print("-" * 60)

    for c in convos:
        created = c.get("created_at", "")[:10]
        name = c.get("conversation_name", c["source_id"])
        print(f"  [{_short_id(c['source_id'])}] {name}")
        print(f"    v8: {c['uuid'][:16]}...  created: {created}")
        if c.get("summary"):
            summary = c["summary"][:120]
            if len(c["summary"]) > 120:
                summary += "..."
            print(f"    {summary}")
        print()


def main():
    parser = argparse.ArgumentParser(
        description="Trace conversation lineage across projects",
    )
    parser.add_argument(
        "identifier",
        nargs="?",
        help="Conversation ID, UUID, or name fragment to trace",
    )
    parser.add_argument(
        "--full-graph",
        action="store_true",
        help="Show the full lineage graph",
    )
    parser.add_argument(
        "--project",
        help="Filter by project name",
    )
    parser.add_argument(
        "--list-projects",
        action="store_true",
        help="List all registered projects",
    )
    parser.add_argument(
        "--list-conversations",
        action="store_true",
        help="List conversations for --project",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Output as JSON",
    )

    args = parser.parse_args()
    db = get_database()

    if args.list_projects:
        if args.json_output:
            projects = list_projects(db=db)
            print(json.dumps(projects, indent=2, default=str))
        else:
            render_projects(db)
        return

    if args.list_conversations:
        if not args.project:
            parser.error("--list-conversations requires --project")
        if args.json_output:
            convos = list_project_conversations(args.project, db=db)
            print(json.dumps(convos, indent=2, default=str))
        else:
            render_project_conversations(args.project, db)
        return

    if args.full_graph:
        if args.json_output:
            edges = get_full_graph(project=args.project, db=db)
            print(json.dumps(edges, indent=2, default=str))
        else:
            render_full_graph(project=args.project, db=db)
        return

    if not args.identifier:
        parser.error(
            "Provide a conversation identifier, or use --full-graph, "
            "--list-projects, or --list-conversations"
        )

    # Resolve the identifier
    doc = resolve_id(args.identifier, db=db)
    if doc:
        conversation_id = doc["source_id"]
        print(f"Resolved: {doc['conversation_name']} "
              f"(project: {doc['project_name']})")
        print(f"  source_id: {doc['source_id']}")
        print(f"  uuid_v8:   {doc['uuid']}")
        print()
    else:
        # Try using the identifier directly as a conversation ID
        conversation_id = args.identifier

    if args.json_output:
        trace = trace_conversation(conversation_id, db=db)
        # Convert sets to lists for JSON serialization
        trace["conversations"] = list(trace["conversations"])
        trace["projects"] = list(trace["projects"])
        print(json.dumps(trace, indent=2, default=str))
    else:
        render_trace(conversation_id, db)


if __name__ == "__main__":
    main()
