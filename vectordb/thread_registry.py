"""Forge OS Layer 2: GRAPH — Thread registry CRUD operations.

Manages the lifecycle of threads (T001, T002, ...) extracted from
compression archives. Threads track open questions, blocked work,
and resolved outcomes across compression hops.
"""

from datetime import datetime, timedelta, timezone

from vectordb.config import (
    COLLECTION_THREAD_REGISTRY,
    EMBEDDING_DIMENSIONS,
    STALE_MAX_DAYS,
    STALE_MAX_HOPS,
)
from vectordb.blob_store import store as blob_store
from vectordb.db import get_database
from vectordb.display_ids import allocate_display_id, register_display_id
from vectordb.embeddings import embed_texts
from vectordb.events import emit_event
from vectordb.uuidv8 import thread_id as derive_thread_uuid


def upsert_thread(
    local_id,
    title,
    project,
    project_uuid,
    first_seen_conversation_id,
    status="open",
    priority="medium",
    blocked_by=None,
    resolution=None,
    epistemic_tier=None,
    db=None,
):
    """Upsert a thread into the registry.

    Generates a deterministic UUIDv8 from (project_uuid, title,
    first_seen_conversation_id). If the thread already exists, updates
    mutable fields; otherwise inserts.

    Args:
        local_id: Archive-local identifier (e.g. "T001").
        title: Thread title text.
        project: Project display name.
        project_uuid: Project UUIDv8 (uuid.UUID).
        first_seen_conversation_id: UUID of originating conversation.
        status: "open", "resolved", or "blocked".
        priority: "high", "medium", or "low".
        blocked_by: Optional list of thread UUIDs blocking this one.
        resolution: Optional resolution text (for resolved threads).
        epistemic_tier: Optional float 0-1 epistemic confidence.
        db: Optional database instance.

    Returns:
        Dict with 'action' ("inserted" or "updated"), 'uuid', and thread doc.
    """
    if db is None:
        db = get_database()

    collection = db[COLLECTION_THREAD_REGISTRY]
    now = datetime.now(timezone.utc)
    thread_uuid = str(derive_thread_uuid(
        project_uuid, title, first_seen_conversation_id
    ))

    existing = collection.find_one({"uuid": thread_uuid})

    title_blob_ref = blob_store(title)
    resolution_blob_ref = blob_store(resolution) if resolution else None

    doc = {
        "uuid": thread_uuid,
        "local_id": local_id,
        "title": title,
        "status": status,
        "project": project,
        "project_uuid": str(project_uuid),
        "first_seen_conversation": str(first_seen_conversation_id),
        "last_updated_conversation": str(first_seen_conversation_id),
        "priority": priority,
        "blocked_by": blocked_by or [],
        "resolution": resolution or "",
        "epistemic_tier": epistemic_tier,
        "hops_since_validated": 0,
        "last_validated": now,
        "updated_at": now.isoformat(),
    }
    if title_blob_ref:
        doc["title_blob_ref"] = title_blob_ref
    if resolution_blob_ref:
        doc["resolution_blob_ref"] = resolution_blob_ref

    if existing is None:
        display_id = allocate_display_id(project, "thread", db=db)
        doc["global_display_id"] = display_id
        doc["created_at"] = now.isoformat()
        try:
            embeddings = embed_texts([title[:8000]])
            doc["embedding"] = embeddings[0] if embeddings else [0.0] * EMBEDDING_DIMENSIONS
        except Exception:
            doc["embedding"] = [0.0] * EMBEDDING_DIMENSIONS
        collection.insert_one(doc)
        register_display_id(
            display_id, thread_uuid, COLLECTION_THREAD_REGISTRY, project, db=db,
        )
        action = "inserted"
    else:
        update_fields = {
            "local_id": local_id,
            "status": status,
            "priority": priority,
            "blocked_by": blocked_by or [],
            "last_updated_conversation": str(first_seen_conversation_id),
            "hops_since_validated": 0,
            "last_validated": now,
            "updated_at": now.isoformat(),
        }
        if resolution:
            update_fields["resolution"] = resolution
            res_ref = blob_store(resolution)
            if res_ref:
                update_fields["resolution_blob_ref"] = res_ref
        if epistemic_tier is not None:
            update_fields["epistemic_tier"] = epistemic_tier
        if existing.get("title") != title:
            try:
                embeddings = embed_texts([title[:8000]])
                update_fields["embedding"] = embeddings[0] if embeddings else [0.0] * EMBEDDING_DIMENSIONS
            except Exception:
                pass
            update_fields["title"] = title
        collection.update_one({"uuid": thread_uuid}, {"$set": update_fields})
        action = "updated"

    emit_event(
        "graph.thread.upserted",
        {
            "uuid": thread_uuid,
            "local_id": local_id,
            "action": action,
            "project": project,
        },
        db=db,
    )

    return {"action": action, "uuid": thread_uuid}


def get_active_threads(project, db=None):
    """Return all non-resolved threads for a project.

    Args:
        project: Project display name.
        db: Optional database instance.

    Returns:
        List of thread documents sorted by priority (high first),
        then updated_at descending.
    """
    if db is None:
        db = get_database()

    collection = db[COLLECTION_THREAD_REGISTRY]
    priority_order = {"high": 0, "medium": 1, "low": 2}

    results = list(
        collection.find(
            {"project": project, "status": {"$ne": "resolved"}},
            {"_id": 0},
        )
    )

    results.sort(
        key=lambda t: (
            priority_order.get(t.get("priority", "medium"), 1),
            t.get("updated_at", ""),
        ),
    )

    return results


def resolve_thread(thread_uuid, resolution, db=None):
    """Mark a thread as resolved.

    Args:
        thread_uuid: The thread's UUIDv8 string.
        resolution: Resolution description text.
        db: Optional database instance.

    Returns:
        Dict with 'action' and 'uuid'.
    """
    if db is None:
        db = get_database()

    collection = db[COLLECTION_THREAD_REGISTRY]
    now = datetime.now(timezone.utc)

    update_fields = {
        "status": "resolved",
        "resolution": resolution,
        "updated_at": now.isoformat(),
    }
    resolution_ref = blob_store(resolution)
    if resolution_ref:
        update_fields["resolution_blob_ref"] = resolution_ref

    collection.update_one(
        {"uuid": thread_uuid},
        {"$set": update_fields},
    )

    emit_event(
        "graph.thread.resolved",
        {"uuid": thread_uuid, "resolution": resolution[:200]},
        db=db,
    )

    return {"action": "resolved", "uuid": thread_uuid}


def get_stale_threads(project, max_hops=None, max_days=None, db=None):
    """Find threads that haven't been validated recently.

    A thread is stale if it exceeds max_hops since last validation
    OR hasn't been validated in max_days.

    Args:
        project: Project display name.
        max_hops: Hop threshold (default from config).
        max_days: Day threshold (default from config).
        db: Optional database instance.

    Returns:
        List of stale thread documents.
    """
    if db is None:
        db = get_database()
    if max_hops is None:
        max_hops = STALE_MAX_HOPS
    if max_days is None:
        max_days = STALE_MAX_DAYS

    collection = db[COLLECTION_THREAD_REGISTRY]
    cutoff = datetime.now(timezone.utc) - timedelta(days=max_days)

    return list(
        collection.find(
            {
                "project": project,
                "status": {"$ne": "resolved"},
                "$or": [
                    {"hops_since_validated": {"$gte": max_hops}},
                    {"last_validated": {"$lte": cutoff}},
                ],
            },
            {"_id": 0},
        )
    )


def increment_thread_hops(project, exclude_uuids=None, db=None):
    """Increment hops_since_validated for all active threads NOT in exclude set.

    Called after a sync to mark threads that were NOT present in the
    latest archive as one hop further from validation.

    Args:
        project: Project display name.
        exclude_uuids: Set/list of thread UUIDs that WERE in the archive.
        db: Optional database instance.

    Returns:
        Number of threads incremented.
    """
    if db is None:
        db = get_database()

    collection = db[COLLECTION_THREAD_REGISTRY]
    query = {
        "project": project,
        "status": {"$ne": "resolved"},
    }
    if exclude_uuids:
        query["uuid"] = {"$nin": list(exclude_uuids)}

    result = collection.update_many(query, {"$inc": {"hops_since_validated": 1}})
    return result.modified_count
