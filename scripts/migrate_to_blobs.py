"""Migrate existing inline text to content-addressed blob store.

Scans MongoDB collections for documents with text fields but no blob_ref,
stores the content as blobs, and writes the ref back to the document.

Usage:
    python scripts/migrate_to_blobs.py --dry-run
    python scripts/migrate_to_blobs.py --collections decision_registry,priming_registry
    python scripts/migrate_to_blobs.py --strip-inline
    python scripts/migrate_to_blobs.py --stats
"""

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from vectordb.blob_store import store as blob_store, store_json as blob_store_json
from vectordb.db import get_database

MIGRATION_MAP = {
    "decision_registry": [
        ("text", "text_blob_ref"),
        ("rationale", "rationale_blob_ref"),
    ],
    "thread_registry": [
        ("title", "title_blob_ref"),
        ("resolution", "resolution_blob_ref"),
    ],
    "priming_registry": [
        ("content", "content_blob_ref"),
    ],
    "expedition_flags": [
        ("description", "description_blob_ref"),
        ("context", "context_blob_ref"),
    ],
    "patterns": [
        ("content", "content_blob_ref"),
    ],
    "archive": [
        ("content_summary", "content_summary_blob_ref"),
    ],
    "published_artifacts": [
        ("content", "content_blob_ref"),
    ],
    "code_sessions": [
        ("summary", "summary_blob_ref"),
    ],
    "message_embeddings": [
        ("text", "text_blob_ref"),
    ],
    "conversation_embeddings": [
        ("summary", "summary_blob_ref"),
    ],
}

JSON_MIGRATION_MAP = {
    "entanglement_scans": [
        ("clusters", "clusters_blob_ref"),
        ("bridges", "bridges_blob_ref"),
        ("loose_ends", "loose_ends_blob_ref"),
    ],
}


def migrate_collection(db, collection_name, field_pairs, dry_run=False,
                        strip_inline=False):
    """Migrate one collection's text fields to blobs.

    Returns dict with stats: docs_processed, blobs_created, bytes_stored.
    """
    collection = db[collection_name]
    stats = {
        "docs_processed": 0,
        "blobs_created": 0,
        "bytes_stored": 0,
        "already_migrated": 0,
    }

    for text_field, ref_field in field_pairs:
        query = {
            text_field: {"$exists": True, "$ne": "", "$ne": None},
            ref_field: {"$exists": False},
        }

        cursor = collection.find(query, {"_id": 1, text_field: 1})
        for doc in cursor:
            text_value = doc.get(text_field)
            if not text_value:
                continue

            content = text_value if isinstance(text_value, str) else str(text_value)
            if not content:
                continue

            stats["docs_processed"] += 1

            if dry_run:
                stats["blobs_created"] += 1
                stats["bytes_stored"] += len(content.encode("utf-8"))
                continue

            blob_ref = blob_store(content)
            if not blob_ref:
                continue

            update = {"$set": {ref_field: blob_ref}}
            if strip_inline:
                thumbnail = content[:200] + "..." if len(content) > 200 else content
                update["$set"][text_field] = thumbnail

            collection.update_one({"_id": doc["_id"]}, update)
            stats["blobs_created"] += 1
            stats["bytes_stored"] += len(content.encode("utf-8"))

        already = collection.count_documents({ref_field: {"$exists": True}})
        stats["already_migrated"] += already

    return stats


def migrate_json_collection(db, collection_name, field_pairs, dry_run=False):
    """Migrate JSON fields (clusters, bridges, etc.) to blobs."""
    collection = db[collection_name]
    stats = {
        "docs_processed": 0,
        "blobs_created": 0,
        "bytes_stored": 0,
        "already_migrated": 0,
    }

    for json_field, ref_field in field_pairs:
        query = {
            json_field: {"$exists": True},
            ref_field: {"$exists": False},
        }

        cursor = collection.find(query, {"_id": 1, json_field: 1})
        for doc in cursor:
            json_value = doc.get(json_field)
            if json_value is None:
                continue

            stats["docs_processed"] += 1

            if dry_run:
                import json
                content = json.dumps(json_value, default=str)
                stats["blobs_created"] += 1
                stats["bytes_stored"] += len(content.encode("utf-8"))
                continue

            blob_ref = blob_store_json(json_value)
            if not blob_ref:
                continue

            collection.update_one(
                {"_id": doc["_id"]},
                {"$set": {ref_field: blob_ref}},
            )
            stats["blobs_created"] += 1

        already = collection.count_documents({ref_field: {"$exists": True}})
        stats["already_migrated"] += already

    return stats


def show_stats(db):
    """Show migration status for all collections."""
    print(f"{'Collection':<30} {'Total':>8} {'Has Ref':>8} {'Missing':>8}")
    print("-" * 58)

    for collection_name, field_pairs in {**MIGRATION_MAP, **JSON_MIGRATION_MAP}.items():
        try:
            total = db[collection_name].count_documents({})
        except Exception:
            continue

        for text_field, ref_field in field_pairs:
            has_ref = db[collection_name].count_documents(
                {ref_field: {"$exists": True}}
            )
            missing = db[collection_name].count_documents({
                text_field: {"$exists": True, "$ne": "", "$ne": None},
                ref_field: {"$exists": False},
            })
            label = f"{collection_name}.{text_field}"
            print(f"{label:<30} {total:>8} {has_ref:>8} {missing:>8}")


def main():
    parser = argparse.ArgumentParser(description="Migrate inline text to blob store")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would be migrated without writing")
    parser.add_argument("--collections", type=str, default=None,
                        help="Comma-separated list of collections to migrate")
    parser.add_argument("--strip-inline", action="store_true",
                        help="Replace inline text with truncated thumbnail")
    parser.add_argument("--stats", action="store_true",
                        help="Show migration status only")

    args = parser.parse_args()
    db = get_database()

    if args.stats:
        show_stats(db)
        return

    target_collections = None
    if args.collections:
        target_collections = set(args.collections.split(","))

    mode = "DRY RUN" if args.dry_run else "LIVE"
    print(f"Blob migration ({mode})")
    print("=" * 60)

    total_stats = {
        "docs_processed": 0,
        "blobs_created": 0,
        "bytes_stored": 0,
        "already_migrated": 0,
    }

    for collection_name, field_pairs in MIGRATION_MAP.items():
        if target_collections and collection_name not in target_collections:
            continue

        print(f"\n  {collection_name}:")
        stats = migrate_collection(
            db, collection_name, field_pairs,
            dry_run=args.dry_run,
            strip_inline=args.strip_inline,
        )
        print(f"    processed={stats['docs_processed']}, "
              f"blobs={stats['blobs_created']}, "
              f"bytes={stats['bytes_stored']:,}, "
              f"already={stats['already_migrated']}")

        for key in total_stats:
            total_stats[key] += stats[key]

    for collection_name, field_pairs in JSON_MIGRATION_MAP.items():
        if target_collections and collection_name not in target_collections:
            continue

        print(f"\n  {collection_name} (JSON):")
        stats = migrate_json_collection(
            db, collection_name, field_pairs,
            dry_run=args.dry_run,
        )
        print(f"    processed={stats['docs_processed']}, "
              f"blobs={stats['blobs_created']}, "
              f"bytes={stats['bytes_stored']:,}, "
              f"already={stats['already_migrated']}")

        for key in total_stats:
            total_stats[key] += stats[key]

    print(f"\n{'=' * 60}")
    print(f"Total: {total_stats['docs_processed']} docs, "
          f"{total_stats['blobs_created']} blobs, "
          f"{total_stats['bytes_stored']:,} bytes")
    print(f"Already migrated: {total_stats['already_migrated']}")


if __name__ == "__main__":
    main()
