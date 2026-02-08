"""Memory event audit log for Forge OS Layer 1: MEMORY."""

from datetime import datetime, timezone

from vectordb.config import COLLECTION_EVENTS, EVENTS_TTL_SECONDS
from vectordb.db import get_database


def emit_event(event_type, details, db=None):
    """Record a memory event in the audit log.

    Args:
        event_type: Event type string, e.g. 'memory.vector.stored',
                    'memory.pattern.matched', 'memory.forget'.
        details: Dict with event details (collection, document_id, action, actor).
        db: Optional database instance.

    Returns:
        The inserted document's _id.
    """
    if db is None:
        db = get_database()

    now = datetime.now(timezone.utc)
    doc = {
        "event_type": event_type,
        "timestamp": now,
        "details": details,
        "expires_at": datetime.fromtimestamp(
            now.timestamp() + EVENTS_TTL_SECONDS, tz=timezone.utc
        ),
    }

    result = db[COLLECTION_EVENTS].insert_one(doc)
    return result.inserted_id


def query_events(event_type=None, since=None, limit=50, db=None):
    """Query memory events from the audit log.

    Args:
        event_type: Optional filter by event type.
        since: Optional datetime — only return events after this time.
        limit: Max results to return.
        db: Optional database instance.

    Returns:
        List of event documents, newest first.
    """
    if db is None:
        db = get_database()

    query = {}
    if event_type:
        query["event_type"] = event_type
    if since:
        query["timestamp"] = {"$gte": since}

    return list(
        db[COLLECTION_EVENTS]
        .find(query, {"_id": 0})
        .sort("timestamp", -1)
        .limit(limit)
    )
