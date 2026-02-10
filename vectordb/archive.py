"""Forge OS Layer 1: MEMORY — archive and forget functions."""

import uuid
from datetime import datetime, timezone

from vectordb.config import (
    COLLECTION_ARCHIVE,
    RETENTION_DAYS_30,
    RETENTION_DAYS_90,
    RETENTION_DAYS_365,
    RETENTION_PERMANENT,
)
from vectordb.blob_store import store as blob_store
from vectordb.db import get_database
from vectordb.events import emit_event

_RETENTION_DAYS = {
    "days_30": RETENTION_DAYS_30,
    "days_90": RETENTION_DAYS_90,
    "days_365": RETENTION_DAYS_365,
    RETENTION_PERMANENT: None,
}


def archive_store(source_collection, source_id, content_summary,
                  retention_policy="days_90", metadata=None, db=None):
    """Archive a document with a retention policy.

    Args:
        source_collection: The collection the document came from.
        source_id: The original document's identifier.
        content_summary: Summary text for the archived entry.
        retention_policy: One of 'days_30', 'days_90', 'days_365', 'permanent'.
        metadata: Optional dict of additional metadata.
        db: Optional database instance.

    Returns:
        The archive document (without _id).
    """
    if db is None:
        db = get_database()

    archive_id = f"arc_{uuid.uuid4().hex[:12]}"
    now = datetime.now(timezone.utc)

    retention_days = _RETENTION_DAYS.get(retention_policy)
    expires_at = None
    if retention_days is not None:
        expires_at = datetime.fromtimestamp(
            now.timestamp() + (retention_days * 86400), tz=timezone.utc
        )

    content_summary_blob_ref = blob_store(content_summary)

    doc = {
        "archive_id": archive_id,
        "source_collection": source_collection,
        "source_id": str(source_id),
        "content_summary": content_summary[:4000],
        "retention_policy": retention_policy,
        "expires_at": expires_at,
        "metadata": metadata or {},
        "created_at": now.isoformat(),
    }
    if content_summary_blob_ref:
        doc["content_summary_blob_ref"] = content_summary_blob_ref

    db[COLLECTION_ARCHIVE].insert_one(doc)

    emit_event(
        "memory.archive.stored",
        {
            "archive_id": archive_id,
            "source_collection": source_collection,
            "source_id": str(source_id),
            "retention_policy": retention_policy,
        },
        db=db,
    )

    return {k: v for k, v in doc.items() if k != "_id"}


def archive_retrieve(source_collection=None, source_id=None, retention_policy=None,
                     limit=20, db=None):
    """Retrieve archived documents with optional filters.

    Args:
        source_collection: Optional filter by source collection.
        source_id: Optional filter by source document ID.
        retention_policy: Optional filter by retention policy.
        limit: Max results.
        db: Optional database instance.

    Returns:
        List of archive documents.
    """
    if db is None:
        db = get_database()

    query = {}
    if source_collection:
        query["source_collection"] = source_collection
    if source_id:
        query["source_id"] = str(source_id)
    if retention_policy:
        query["retention_policy"] = retention_policy

    return list(
        db[COLLECTION_ARCHIVE]
        .find(query, {"_id": 0})
        .sort("created_at", -1)
        .limit(limit)
    )


def forget(source_collection, source_id, db=None):
    """Permanently remove a document and its archive entries.

    Deletes from both the source collection and the archive,
    then logs a forget event.

    Args:
        source_collection: The collection containing the original document.
        source_id: The document's identifier field value.
        db: Optional database instance.

    Returns:
        Dict with 'source_deleted' and 'archive_deleted' counts.
    """
    if db is None:
        db = get_database()

    # Identify the correct ID field per collection
    id_field_map = {
        "message_embeddings": "conversation_id",
        "conversation_embeddings": "conversation_id",
        "document_embeddings": "source_id",
        "patterns": "pattern_id",
    }
    id_field = id_field_map.get(source_collection, "_id")

    source_result = db[source_collection].delete_many({id_field: source_id})
    archive_result = db[COLLECTION_ARCHIVE].delete_many({
        "source_collection": source_collection,
        "source_id": str(source_id),
    })

    emit_event(
        "memory.forget",
        {
            "source_collection": source_collection,
            "source_id": str(source_id),
            "source_deleted": source_result.deleted_count,
            "archive_deleted": archive_result.deleted_count,
        },
        db=db,
    )

    return {
        "source_deleted": source_result.deleted_count,
        "archive_deleted": archive_result.deleted_count,
    }
