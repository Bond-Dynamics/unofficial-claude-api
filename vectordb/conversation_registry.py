"""Forge OS Layer 2: GRAPH — Conversation identity registry.

Maps Claude v4 conversation UUIDs to deterministic UUIDv8 identifiers
and stores project membership. Enables cross-project lineage tracing
and conversation handoff tracking.

Each conversation gets a UUIDv8 derived from:
    v8_from_string(name=source_id, namespace=project_uuid, timestamp_ms=created_at_ms)

Where source_id is the original Claude v4 UUID (or conversation name
if no UUID is available).
"""

from datetime import datetime, timezone

from vectordb.config import COLLECTION_CONVERSATION_REGISTRY
from vectordb.db import get_database
from vectordb.events import emit_event
from vectordb.uuidv8 import v5, v8_from_string


def _derive_project_uuid(project_name):
    """Derive a stable project UUID from name only (UUIDv5).

    Uses UUIDv5 (not v8) because projects are singletons keyed by name,
    not by time. Same project name always produces the same UUID.
    """
    return v5(f"project:{project_name}")


def _derive_conversation_v8(source_id, project_uuid, created_at_ms):
    """Derive a deterministic UUIDv8 for a conversation.

    Uses the source identifier (Claude v4 UUID or name) as the
    content seed, the project UUID as namespace, and the conversation's
    creation timestamp for time-ordering.
    """
    return str(v8_from_string(
        name=source_id,
        namespace=project_uuid,
        timestamp_ms=created_at_ms,
    ))


def _parse_timestamp(created_at):
    """Parse a created_at value into (ms_timestamp, iso_string)."""
    now = datetime.now(timezone.utc)

    if created_at is None:
        return int(now.timestamp() * 1000), now.isoformat()

    if isinstance(created_at, str):
        dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        return int(dt.timestamp() * 1000), created_at

    if isinstance(created_at, datetime):
        return int(created_at.timestamp() * 1000), created_at.isoformat()

    return int(created_at), datetime.fromtimestamp(
        created_at / 1000, tz=timezone.utc
    ).isoformat()


def register_conversation(
    source_id,
    project_name,
    conversation_name=None,
    created_at=None,
    summary=None,
    db=None,
):
    """Register a conversation, mapping its source ID to UUIDv8.

    Args:
        source_id: Original identifier (Claude v4 UUID or name string).
        project_name: Project this conversation belongs to.
        conversation_name: Human-readable conversation name.
        created_at: ISO 8601 timestamp, datetime, or epoch ms.
        summary: Optional conversation summary (truncated to 2000 chars).
        db: Optional database instance.

    Returns:
        Dict with 'action' ("inserted" or "updated"), 'uuid', 'project_uuid'.
    """
    if db is None:
        db = get_database()

    collection = db[COLLECTION_CONVERSATION_REGISTRY]
    now = datetime.now(timezone.utc)

    created_at_ms, created_at_iso = _parse_timestamp(created_at)
    project_uuid = _derive_project_uuid(project_name)
    conv_uuid = _derive_conversation_v8(source_id, project_uuid, created_at_ms)

    existing = collection.find_one({"source_id": source_id})

    if existing is not None:
        update_fields = {"updated_at": now.isoformat()}
        if conversation_name:
            update_fields["conversation_name"] = conversation_name
        if summary:
            update_fields["summary"] = summary[:2000]

        collection.update_one({"source_id": source_id}, {"$set": update_fields})
        action = "updated"
    else:
        doc = {
            "uuid": conv_uuid,
            "source_id": source_id,
            "project_name": project_name,
            "project_uuid": str(project_uuid),
            "conversation_name": conversation_name or source_id,
            "summary": (summary or "")[:2000],
            "created_at": created_at_iso,
            "created_at_ms": created_at_ms,
            "updated_at": now.isoformat(),
        }
        collection.insert_one(doc)
        action = "inserted"

    emit_event(
        "graph.conversation.registered",
        {
            "uuid": conv_uuid,
            "source_id": source_id,
            "project": project_name,
            "action": action,
        },
        db=db,
    )

    return {
        "action": action,
        "uuid": conv_uuid,
        "project_uuid": str(project_uuid),
    }


def get_conversation(source_id, db=None):
    """Look up a conversation by its source ID (Claude v4 UUID).

    Returns:
        Conversation document or None.
    """
    if db is None:
        db = get_database()

    return db[COLLECTION_CONVERSATION_REGISTRY].find_one(
        {"source_id": source_id},
        {"_id": 0},
    )


def get_conversation_by_uuid(conv_uuid, db=None):
    """Look up a conversation by its UUIDv8.

    Returns:
        Conversation document or None.
    """
    if db is None:
        db = get_database()

    return db[COLLECTION_CONVERSATION_REGISTRY].find_one(
        {"uuid": conv_uuid},
        {"_id": 0},
    )


def list_project_conversations(project_name, db=None):
    """List all conversations for a project, sorted by creation time.

    Returns:
        List of conversation documents.
    """
    if db is None:
        db = get_database()

    return list(
        db[COLLECTION_CONVERSATION_REGISTRY].find(
            {"project_name": project_name},
            {"_id": 0},
        ).sort("created_at_ms", -1)
    )


def list_projects(db=None):
    """List all registered projects with conversation counts.

    Returns:
        List of dicts with project_name, project_uuid, conversation_count,
        earliest_at, latest_at.
    """
    if db is None:
        db = get_database()

    pipeline = [
        {
            "$group": {
                "_id": "$project_name",
                "project_uuid": {"$first": "$project_uuid"},
                "count": {"$sum": 1},
                "earliest": {"$min": "$created_at_ms"},
                "latest": {"$max": "$created_at_ms"},
            }
        },
        {"$sort": {"count": -1}},
    ]
    results = list(
        db[COLLECTION_CONVERSATION_REGISTRY].aggregate(pipeline)
    )
    return [
        {
            "project_name": r["_id"],
            "project_uuid": r["project_uuid"],
            "conversation_count": r["count"],
            "earliest_at": r["earliest"],
            "latest_at": r["latest"],
        }
        for r in results
    ]


def resolve_id(identifier, db=None):
    """Resolve any identifier to a conversation document.

    Tries in order:
      1. Exact source_id match
      2. Exact uuid match
      3. Prefix match on source_id (min 4 chars)
      4. Case-insensitive substring match on conversation_name

    Returns:
        Conversation document or None.
    """
    if db is None:
        db = get_database()

    collection = db[COLLECTION_CONVERSATION_REGISTRY]

    doc = collection.find_one({"source_id": identifier}, {"_id": 0})
    if doc:
        return doc

    doc = collection.find_one({"uuid": identifier}, {"_id": 0})
    if doc:
        return doc

    if len(identifier) >= 4:
        doc = collection.find_one(
            {"source_id": {"$regex": f"^{identifier}"}},
            {"_id": 0},
        )
        if doc:
            return doc

    doc = collection.find_one(
        {"conversation_name": {"$regex": identifier, "$options": "i"}},
        {"_id": 0},
    )
    return doc
