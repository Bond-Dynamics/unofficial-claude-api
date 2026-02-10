"""Forge OS Layer 1: MEMORY — scratchpad TTL key-value store."""

import json
from datetime import datetime, timezone

from pymongo.errors import DuplicateKeyError

from vectordb.config import COLLECTION_SCRATCHPAD, SCRATCHPAD_DEFAULT_TTL
from vectordb.db import get_database


def scratchpad_set(context_id, key, value, ttl=None, db=None):
    """Set a key-value pair in the scratchpad with TTL.

    Args:
        context_id: Isolation namespace (e.g. session ID).
        key: Key string.
        value: Any JSON-serializable value.
        ttl: Time-to-live in seconds. Defaults to SCRATCHPAD_DEFAULT_TTL.
        db: Optional database instance.

    Returns:
        True if set successfully.
    """
    if db is None:
        db = get_database()

    if ttl is None:
        ttl = SCRATCHPAD_DEFAULT_TTL

    now = datetime.now(timezone.utc)
    expires_at = datetime.fromtimestamp(now.timestamp() + ttl, tz=timezone.utc)

    doc = {
        "context_id": context_id,
        "key": key,
        "value": json.dumps(value),
        "expires_at": expires_at,
        "updated_at": now.isoformat(),
    }

    db[COLLECTION_SCRATCHPAD].update_one(
        {"context_id": context_id, "key": key},
        {"$set": doc},
        upsert=True,
    )

    return True


def scratchpad_get(context_id, key, db=None):
    """Get a value from the scratchpad.

    Args:
        context_id: Isolation namespace.
        key: Key string.
        db: Optional database instance.

    Returns:
        The stored value (deserialized from JSON), or None if not found/expired.
    """
    if db is None:
        db = get_database()

    doc = db[COLLECTION_SCRATCHPAD].find_one(
        {"context_id": context_id, "key": key}
    )

    if doc is None:
        return None

    # MongoDB TTL cleanup is not instant — check manually too
    if doc.get("expires_at") and doc["expires_at"] < datetime.now(timezone.utc):
        return None

    try:
        return json.loads(doc["value"])
    except (json.JSONDecodeError, TypeError):
        return doc.get("value")


def scratchpad_delete(context_id, key, db=None):
    """Delete a specific key from the scratchpad.

    Args:
        context_id: Isolation namespace.
        key: Key string.
        db: Optional database instance.

    Returns:
        True if deleted, False if not found.
    """
    if db is None:
        db = get_database()

    result = db[COLLECTION_SCRATCHPAD].delete_one(
        {"context_id": context_id, "key": key}
    )
    return result.deleted_count > 0


def scratchpad_clear(context_id, db=None):
    """Delete all keys for a given context.

    Args:
        context_id: Isolation namespace to clear.
        db: Optional database instance.

    Returns:
        Number of entries deleted.
    """
    if db is None:
        db = get_database()

    result = db[COLLECTION_SCRATCHPAD].delete_many({"context_id": context_id})
    return result.deleted_count


def scratchpad_list(context_id, db=None):
    """List all keys and values for a context.

    Args:
        context_id: Isolation namespace.
        db: Optional database instance.

    Returns:
        Dict of {key: value} pairs.
    """
    if db is None:
        db = get_database()

    now = datetime.now(timezone.utc)
    docs = db[COLLECTION_SCRATCHPAD].find(
        {"context_id": context_id, "expires_at": {"$gt": now}},
        {"_id": 0, "key": 1, "value": 1},
    )

    result = {}
    for doc in docs:
        try:
            result[doc["key"]] = json.loads(doc["value"])
        except (json.JSONDecodeError, TypeError):
            result[doc["key"]] = doc.get("value")

    return result
