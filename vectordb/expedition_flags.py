"""Forge OS Layer 2.5: EXPEDITION — Persistent expedition flags.

Stores "flag this" bookmarks from expedition conversations in MongoDB
so they survive context compression and session boundaries. Flags are
lightweight markers that can later be compiled into full findings.
"""

from datetime import datetime, timezone

from vectordb.config import COLLECTION_EXPEDITION_FLAGS
from vectordb.db import get_database
from vectordb.events import emit_event
from vectordb.uuidv8 import v5


def _derive_flag_uuid(project_uuid, description, conversation_id):
    """Deterministic UUID for a flag: project + description + conversation.

    Uses UUIDv5 (not v8) because flags are keyed by content, not by time.
    Same description + conversation always gets the same UUID.
    """
    content = f"flag:{description}:{conversation_id}"
    return str(v5(content, namespace=project_uuid))


def plant_flag(
    description,
    project,
    project_uuid,
    conversation_id,
    category=None,
    context=None,
    db=None,
):
    """Plant a persistent expedition flag.

    Args:
        description: What was flagged (the finding/observation).
        project: Project display name.
        project_uuid: Project UUIDv8 (uuid.UUID).
        conversation_id: UUID string of the conversation where flagged.
        category: Optional category (inversion, isomorphism, fsd,
            manifestation, trap, general).
        context: Optional surrounding context text.
        db: Optional database instance.

    Returns:
        Dict with 'action' ("inserted" or "existing"), 'uuid'.
    """
    if db is None:
        db = get_database()

    collection = db[COLLECTION_EXPEDITION_FLAGS]
    now = datetime.now(timezone.utc)

    flag_uuid = _derive_flag_uuid(project_uuid, description, conversation_id)
    existing = collection.find_one({"uuid": flag_uuid})

    if existing is not None:
        return {"action": "existing", "uuid": flag_uuid}

    doc = {
        "uuid": flag_uuid,
        "description": description[:4000],
        "project": project,
        "project_uuid": str(project_uuid),
        "conversation_id": str(conversation_id),
        "category": category or "general",
        "context": (context or "")[:8000],
        "status": "pending",
        "compiled_into": None,
        "created_at": now.isoformat(),
        "updated_at": now.isoformat(),
    }

    collection.insert_one(doc)

    emit_event(
        "expedition.flag.planted",
        {
            "uuid": flag_uuid,
            "project": project,
            "category": category or "general",
        },
        db=db,
    )

    return {"action": "inserted", "uuid": flag_uuid}


def get_pending_flags(project, db=None):
    """Get all uncompiled flags for a project.

    Args:
        project: Project display name.
        db: Optional database instance.

    Returns:
        List of pending flag documents, newest first.
    """
    if db is None:
        db = get_database()

    collection = db[COLLECTION_EXPEDITION_FLAGS]
    return list(
        collection.find(
            {"project": project, "status": "pending"},
            {"_id": 0},
        ).sort("created_at", -1)
    )


def get_flags_by_category(project, category, db=None):
    """Get pending flags for a project filtered by category.

    Args:
        project: Project display name.
        category: Flag category to filter by.
        db: Optional database instance.

    Returns:
        List of matching flag documents.
    """
    if db is None:
        db = get_database()

    collection = db[COLLECTION_EXPEDITION_FLAGS]
    return list(
        collection.find(
            {"project": project, "status": "pending", "category": category},
            {"_id": 0},
        ).sort("created_at", -1)
    )


def mark_flag_compiled(flag_uuid, compiled_into, db=None):
    """Mark a flag as compiled into an expedition compilation.

    Args:
        flag_uuid: The flag's UUID string.
        compiled_into: Expedition ID or priming block UUID it was compiled into.
        db: Optional database instance.

    Returns:
        Dict with 'action' and 'uuid'.
    """
    if db is None:
        db = get_database()

    collection = db[COLLECTION_EXPEDITION_FLAGS]
    now = datetime.now(timezone.utc)

    collection.update_one(
        {"uuid": flag_uuid},
        {
            "$set": {
                "status": "compiled",
                "compiled_into": compiled_into,
                "updated_at": now.isoformat(),
            }
        },
    )

    emit_event(
        "expedition.flag.compiled",
        {"uuid": flag_uuid, "compiled_into": compiled_into},
        db=db,
    )

    return {"action": "compiled", "uuid": flag_uuid}


def delete_flag(flag_uuid, db=None):
    """Delete a flag.

    Args:
        flag_uuid: The flag's UUID string.
        db: Optional database instance.

    Returns:
        Dict with 'action' and 'uuid'.
    """
    if db is None:
        db = get_database()

    collection = db[COLLECTION_EXPEDITION_FLAGS]
    collection.delete_one({"uuid": flag_uuid})

    return {"action": "deleted", "uuid": flag_uuid}


def get_all_flags(project, include_compiled=False, db=None):
    """Get all flags for a project.

    Args:
        project: Project display name.
        include_compiled: If True, include already-compiled flags.
        db: Optional database instance.

    Returns:
        List of flag documents, newest first.
    """
    if db is None:
        db = get_database()

    collection = db[COLLECTION_EXPEDITION_FLAGS]
    query = {"project": project}
    if not include_compiled:
        query["status"] = "pending"

    return list(
        collection.find(query, {"_id": 0}).sort("created_at", -1)
    )
