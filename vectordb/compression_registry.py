"""Forge OS Layer 2: GRAPH — Compression tag registry.

Tracks every compression event as a first-class entity, enabling
queries like "show all compressions this week" and "what decisions
came from this compression?" Also stores a content checksum to
detect post-sync archive modifications.
"""

import hashlib
from datetime import datetime, timezone

from vectordb.config import COLLECTION_COMPRESSION_REGISTRY
from vectordb.db import get_database
from vectordb.events import emit_event


def register_compression(
    compression_tag,
    project,
    source_conversation,
    decisions_captured=None,
    threads_captured=None,
    artifacts_captured=None,
    archive_checksum=None,
    target_conversations=None,
    metadata=None,
    db=None,
):
    """Register a compression event in the registry.

    Upserts by compression_tag. On re-sync, updates target_conversations
    via $addToSet to support branching (one archive -> multiple continuations).

    Args:
        compression_tag: Unique tag identifying this compression event.
        project: Project display name.
        source_conversation: UUID string of the compressed conversation.
        decisions_captured: List of decision local_ids (e.g. ["D001", "D002"]).
        threads_captured: List of thread local_ids (e.g. ["T001"]).
        artifacts_captured: List of artifact local_ids (e.g. ["A001"]).
        archive_checksum: SHA-256 hex digest of the raw archive content.
        target_conversations: List of continuation conversation UUID strings.
        metadata: Optional dict of additional metadata.
        db: Optional database instance.

    Returns:
        Dict with 'action' ("inserted" or "updated") and 'compression_tag'.
    """
    if db is None:
        db = get_database()

    collection = db[COLLECTION_COMPRESSION_REGISTRY]
    now = datetime.now(timezone.utc)

    existing = collection.find_one({"compression_tag": compression_tag})

    if existing is None:
        doc = {
            "compression_tag": compression_tag,
            "project": project,
            "source_conversation": source_conversation,
            "target_conversations": target_conversations or [],
            "decisions_captured": decisions_captured or [],
            "threads_captured": threads_captured or [],
            "artifacts_captured": artifacts_captured or [],
            "checksum": archive_checksum or "",
            "metadata": metadata or {},
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
        }
        collection.insert_one(doc)
        action = "inserted"
    else:
        update = {
            "$set": {
                "updated_at": now.isoformat(),
            }
        }

        add_to_set = {}
        if target_conversations:
            add_to_set["target_conversations"] = {"$each": target_conversations}
        if decisions_captured:
            add_to_set["decisions_captured"] = {"$each": decisions_captured}
        if threads_captured:
            add_to_set["threads_captured"] = {"$each": threads_captured}
        if artifacts_captured:
            add_to_set["artifacts_captured"] = {"$each": artifacts_captured}
        if add_to_set:
            update["$addToSet"] = add_to_set

        if archive_checksum and existing.get("checksum") != archive_checksum:
            update["$set"]["checksum"] = archive_checksum

        collection.update_one({"compression_tag": compression_tag}, update)
        action = "updated"

    emit_event(
        "graph.compression.registered",
        {
            "compression_tag": compression_tag,
            "project": project,
            "action": action,
            "decisions_count": len(decisions_captured or []),
            "threads_count": len(threads_captured or []),
        },
        db=db,
    )

    return {"action": action, "compression_tag": compression_tag}


def get_compression(compression_tag, db=None):
    """Retrieve a single compression record by tag.

    Args:
        compression_tag: The compression tag string.
        db: Optional database instance.

    Returns:
        Compression document dict, or None if not found.
    """
    if db is None:
        db = get_database()

    return db[COLLECTION_COMPRESSION_REGISTRY].find_one(
        {"compression_tag": compression_tag},
        {"_id": 0},
    )


def list_compressions(project, since=None, limit=50, db=None):
    """List compression events for a project, newest first.

    Args:
        project: Project display name.
        since: Optional datetime — only return events after this time.
        limit: Max results.
        db: Optional database instance.

    Returns:
        List of compression documents.
    """
    if db is None:
        db = get_database()

    query = {"project": project}
    if since:
        query["created_at"] = {"$gte": since.isoformat()}

    return list(
        db[COLLECTION_COMPRESSION_REGISTRY]
        .find(query, {"_id": 0})
        .sort("created_at", -1)
        .limit(limit)
    )


def verify_checksum(compression_tag, archive_text, db=None):
    """Verify that an archive's content matches its stored checksum.

    Args:
        compression_tag: The compression tag to verify.
        archive_text: The raw archive markdown text.
        db: Optional database instance.

    Returns:
        Dict with 'match' (bool), 'stored' checksum, and 'computed' checksum.
        Returns None if compression_tag not found.
    """
    if db is None:
        db = get_database()

    record = get_compression(compression_tag, db=db)
    if record is None:
        return None

    computed = hashlib.sha256(archive_text.encode("utf-8")).hexdigest()
    stored = record.get("checksum", "")

    return {
        "match": computed == stored,
        "stored": stored,
        "computed": computed,
    }


def compute_checksum(text):
    """Compute SHA-256 checksum of archive text.

    Args:
        text: Raw archive markdown text.

    Returns:
        Hex digest string.
    """
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
