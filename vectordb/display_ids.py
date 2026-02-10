"""Forge OS Layer 2: GRAPH — Global display ID allocation.

Assigns human-readable, globally unique identifiers in PROJECT-TYPE-SEQUENCE
format (e.g., FORGE-D-0042). Uses MongoDB atomic counters for sequence
allocation, preventing race conditions on concurrent inserts.

Each entity (decision, thread) gets a display ID on first insert. The
mapping display_id -> (uuid, collection) is stored in a lookup index for
reverse resolution.
"""

from datetime import datetime, timezone

from pymongo import ReturnDocument

from vectordb.config import (
    COLLECTION_DISPLAY_ID_COUNTERS,
    COLLECTION_DISPLAY_ID_INDEX,
)
from vectordb.db import get_database


# ---------------------------------------------------------------------------
# Default project prefix map
# ---------------------------------------------------------------------------

DEFAULT_PREFIX_MAP = {
    "Forge OS": "FORGE",
    "The Nexus": "NEXUS",
    "Reality Compiler": "RC",
    "Consciousness Physics": "CPHYS",
    "Wavelength": "WAVE",
    "Attention Currency": "ATTN",
    "Applied Alchemy": "AALCH",
    "Cartographer's Codex": "CODEX",
    "The Evaluator": "EVAL",
    "The Arbiter": "ARBITER",
    "Mission Control": "MISSION",
    "The Guardian": "GUARD",
}

ENTITY_TYPE_MAP = {
    "decision": "D",
    "thread": "T",
    "artifact": "A",
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_project_prefix(project_name, db=None):
    """Get or create a short prefix for a project name.

    Resolution order:
      1. Check DB for a previously stored prefix
      2. Check DEFAULT_PREFIX_MAP
      3. Auto-generate from project name (uppercase, max 5 chars)

    Auto-generated prefixes are persisted to DB for stability.

    Args:
        project_name: Project display name (e.g., "Forge OS").
        db: Optional database instance.

    Returns:
        Uppercase prefix string (e.g., "FORGE").
    """
    if db is None:
        db = get_database()

    counters = db[COLLECTION_DISPLAY_ID_COUNTERS]

    # Check if any counter already exists for this project
    existing = counters.find_one({"project_name": project_name})
    if existing:
        return existing["project_prefix"]

    # Check default map
    if project_name in DEFAULT_PREFIX_MAP:
        return DEFAULT_PREFIX_MAP[project_name]

    # Auto-generate: take uppercase alphanumeric chars, max 5
    prefix = "".join(
        c for c in project_name.upper() if c.isalnum()
    )[:5]
    return prefix or "PROJ"


def allocate_display_id(project_name, entity_type, db=None):
    """Atomically allocate the next global display ID.

    Uses MongoDB findOneAndUpdate with $inc for atomic counter
    increment. Same inputs on concurrent calls produce different
    sequence numbers.

    Args:
        project_name: Project display name (e.g., "Forge OS").
        entity_type: Entity type key ("decision", "thread", "artifact").
        db: Optional database instance.

    Returns:
        Display ID string (e.g., "FORGE-D-0042").
    """
    if db is None:
        db = get_database()

    prefix = get_project_prefix(project_name, db=db)
    type_code = ENTITY_TYPE_MAP.get(entity_type, entity_type[0].upper())

    counters = db[COLLECTION_DISPLAY_ID_COUNTERS]

    result = counters.find_one_and_update(
        {
            "project_prefix": prefix,
            "entity_type": type_code,
        },
        {
            "$inc": {"next_sequence": 1},
            "$setOnInsert": {
                "project_name": project_name,
                "project_prefix": prefix,
                "entity_type": type_code,
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
        },
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )

    sequence = result["next_sequence"]
    return f"{prefix}-{type_code}-{sequence:04d}"


def register_display_id(display_id, entity_uuid, collection_name, project_name, db=None):
    """Record the mapping from display_id to entity UUID.

    Enables reverse lookup: given "FORGE-D-0042", find the UUID and
    which collection it lives in.

    Args:
        display_id: The allocated display ID string.
        entity_uuid: The entity's UUID string.
        collection_name: MongoDB collection name (e.g., "decision_registry").
        project_name: Project display name.
        db: Optional database instance.
    """
    if db is None:
        db = get_database()

    index = db[COLLECTION_DISPLAY_ID_INDEX]
    now = datetime.now(timezone.utc).isoformat()

    index.update_one(
        {"display_id": display_id},
        {
            "$set": {
                "display_id": display_id,
                "entity_uuid": entity_uuid,
                "collection": collection_name,
                "project": project_name,
                "updated_at": now,
            },
            "$setOnInsert": {"created_at": now},
        },
        upsert=True,
    )


def resolve_display_id(display_id, db=None):
    """Look up an entity by its global display ID.

    Args:
        display_id: Display ID string (e.g., "FORGE-D-0042").
        db: Optional database instance.

    Returns:
        Dict with 'entity_uuid', 'collection', 'project', or None if
        not found.
    """
    if db is None:
        db = get_database()

    return db[COLLECTION_DISPLAY_ID_INDEX].find_one(
        {"display_id": display_id},
        {"_id": 0},
    )


def bulk_backfill(project_name, entity_type, collection_name, db=None):
    """Assign display IDs to all existing entities that lack one.

    Processes entities in created_at order so sequence numbers reflect
    chronological insertion order.

    Args:
        project_name: Project display name.
        entity_type: Entity type key ("decision" or "thread").
        collection_name: MongoDB collection name.
        db: Optional database instance.

    Returns:
        Number of display IDs assigned.
    """
    if db is None:
        db = get_database()

    collection = db[collection_name]
    count = 0

    cursor = collection.find(
        {
            "project": project_name,
            "global_display_id": {"$exists": False},
        },
    ).sort("created_at", 1)

    for doc in cursor:
        display_id = allocate_display_id(project_name, entity_type, db=db)

        collection.update_one(
            {"_id": doc["_id"]},
            {"$set": {"global_display_id": display_id}},
        )

        register_display_id(
            display_id,
            doc["uuid"],
            collection_name,
            project_name,
            db=db,
        )
        count += 1

    return count
