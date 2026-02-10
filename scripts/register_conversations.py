#!/usr/bin/env python3
"""Forge OS — Register all existing conversations with UUIDv8 identity.

One-time migration script that reads all conversations from
conversation_embeddings and registers them in conversation_registry
with deterministic UUIDv8 identifiers derived from:

    v8_from_string(
        name=conversation_id,  # Claude v4 UUID
        namespace=project_uuid,  # derived from project name
        timestamp_ms=created_at_ms,
    )

Also backfills project metadata onto existing lineage edges.

Usage:
    python scripts/register_conversations.py
    python scripts/register_conversations.py --dry-run
    python scripts/register_conversations.py --project "Cheeky"
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from vectordb.config import (
    COLLECTION_CONVERSATIONS,
    COLLECTION_LINEAGE_EDGES,
)
from vectordb.conversation_registry import register_conversation
from vectordb.db import get_database


def migrate_conversations(project_filter=None, dry_run=False, db=None):
    """Register all conversations from conversation_embeddings.

    Args:
        project_filter: Optional project name to filter by.
        dry_run: If True, count without writing.
        db: Optional database instance.

    Returns:
        Summary dict with counts.
    """
    if db is None:
        db = get_database()

    source = db[COLLECTION_CONVERSATIONS]

    query = {}
    if project_filter:
        query["project_name"] = project_filter

    cursor = source.find(query, {"_id": 0, "embedding": 0})

    summary = {
        "total": 0,
        "inserted": 0,
        "updated": 0,
        "errors": 0,
        "by_project": {},
    }

    for doc in cursor:
        summary["total"] += 1
        source_id = doc.get("conversation_id", "")
        project_name = doc.get("project_name", "No Project")
        conversation_name = doc.get("name", source_id)
        created_at = doc.get("created_at")
        conv_summary = doc.get("summary", "")

        if not source_id:
            summary["errors"] += 1
            continue

        if dry_run:
            summary.setdefault("by_project", {})
            summary["by_project"][project_name] = (
                summary["by_project"].get(project_name, 0) + 1
            )
            continue

        try:
            result = register_conversation(
                source_id=source_id,
                project_name=project_name,
                conversation_name=conversation_name,
                created_at=created_at,
                summary=conv_summary,
                db=db,
            )

            if result["action"] == "inserted":
                summary["inserted"] += 1
            else:
                summary["updated"] += 1

            summary["by_project"][project_name] = (
                summary["by_project"].get(project_name, 0) + 1
            )
        except Exception as err:
            summary["errors"] += 1
            print(f"  Error registering {source_id[:8]}...: {err}")

    return summary


def backfill_lineage_projects(db=None):
    """Add project metadata to existing lineage edges.

    Looks up each edge's source and target conversations in the
    conversation_registry and writes their project names onto the edge.

    Returns:
        Count of edges updated.
    """
    if db is None:
        db = get_database()

    from vectordb.conversation_registry import get_conversation

    edges_coll = db[COLLECTION_LINEAGE_EDGES]
    edges = list(edges_coll.find({}, {"_id": 0}))

    updated = 0
    for edge in edges:
        updates = {}

        if not edge.get("source_project"):
            src_doc = get_conversation(edge["source_conversation"], db=db)
            if src_doc:
                updates["source_project"] = src_doc["project_name"]

        if not edge.get("target_project"):
            tgt_doc = get_conversation(edge["target_conversation"], db=db)
            if tgt_doc:
                updates["target_project"] = tgt_doc["project_name"]

        if updates:
            edges_coll.update_one(
                {"edge_uuid": edge["edge_uuid"]},
                {"$set": updates},
            )
            updated += 1

    return updated


def main():
    parser = argparse.ArgumentParser(
        description="Register existing conversations with UUIDv8 identity",
    )
    parser.add_argument(
        "--project",
        help="Only register conversations for this project",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Count conversations without writing",
    )
    parser.add_argument(
        "--skip-lineage-backfill",
        action="store_true",
        help="Skip backfilling project metadata onto lineage edges",
    )

    args = parser.parse_args()
    db = get_database()

    print("Registering conversations with UUIDv8 identity...")
    if args.project:
        print(f"  Filtering: {args.project}")
    if args.dry_run:
        print("  [DRY RUN]")

    summary = migrate_conversations(
        project_filter=args.project,
        dry_run=args.dry_run,
        db=db,
    )

    print(f"\nConversation registration {'(dry run)' if args.dry_run else 'complete'}:")
    print(f"  Total processed: {summary['total']}")
    if not args.dry_run:
        print(f"  Inserted: {summary['inserted']}")
        print(f"  Updated: {summary['updated']}")
    if summary["errors"]:
        print(f"  Errors: {summary['errors']}")

    print(f"\nBy project:")
    for project, count in sorted(
        summary["by_project"].items(), key=lambda x: -x[1]
    ):
        print(f"  {project}: {count}")

    if not args.dry_run and not args.skip_lineage_backfill:
        print("\nBackfilling project metadata onto lineage edges...")
        edges_updated = backfill_lineage_projects(db=db)
        print(f"  Edges updated: {edges_updated}")

    print("\nDone.")


if __name__ == "__main__":
    main()
