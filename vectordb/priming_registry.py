"""Forge OS Layer 2.5: EXPEDITION — Priming block registry.

Stores compiled priming blocks from expedition-compiler with territory
keys embedded as vectors. Enables semantic activation: when a future
conversation enters territory matching a priming block's keys, the
block can be retrieved automatically via vector search.
"""

import hashlib
from datetime import datetime, timezone

from vectordb.config import (
    COLLECTION_PRIMING_REGISTRY,
    EMBEDDING_DIMENSIONS,
    PRIMING_TERRITORY_MATCH_THRESHOLD,
    VECTOR_INDEX_NAME,
)
from vectordb.blob_store import store as blob_store
from vectordb.db import get_database
from vectordb.embeddings import embed_texts
from vectordb.events import emit_event
from vectordb.uuidv8 import v5


def _derive_priming_uuid(project_uuid, territory_name):
    """Deterministic UUID for a priming block: project + territory.

    Uses UUIDv5 (not v8) because priming blocks are keyed by territory
    name, not by time. The same territory always gets the same UUID
    regardless of when the block was created.
    """
    return str(v5(f"priming:{territory_name}", namespace=project_uuid))


def upsert_priming_block(
    territory_name,
    territory_keys,
    content,
    project,
    project_uuid,
    source_expedition=None,
    confidence_floor=0.3,
    findings_count=None,
    db=None,
):
    """Upsert a priming block into the registry.

    Embeds territory keys for semantic matching. If a block for the
    same territory already exists, merges (updates content, re-embeds).

    Args:
        territory_name: Human-readable territory label.
        territory_keys: Comma-separated or list of activation keywords.
        content: Full priming block markdown content.
        project: Project display name.
        project_uuid: Project UUIDv8 (uuid.UUID).
        source_expedition: Optional expedition ID (e.g. "EXP-001").
        confidence_floor: Lowest tier included (default 0.3).
        findings_count: Optional dict of finding counts by category.
        db: Optional database instance.

    Returns:
        Dict with 'action' ("inserted" or "updated"), 'uuid'.
    """
    if db is None:
        db = get_database()

    collection = db[COLLECTION_PRIMING_REGISTRY]
    now = datetime.now(timezone.utc)

    priming_uuid = _derive_priming_uuid(project_uuid, territory_name)

    if isinstance(territory_keys, list):
        keys_text = ", ".join(territory_keys)
        keys_list = territory_keys
    else:
        keys_text = territory_keys
        keys_list = [k.strip() for k in territory_keys.split(",") if k.strip()]

    content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]

    embeddings = embed_texts([keys_text[:8000]])
    embedding = embeddings[0] if embeddings else [0.0] * EMBEDDING_DIMENSIONS

    existing = collection.find_one({"uuid": priming_uuid})

    content_blob_ref = blob_store(content)

    if existing is not None:
        update_fields = {
            "territory_keys": keys_list,
            "territory_keys_text": keys_text,
            "content": content[:16000],
            "content_hash": content_hash,
            "embedding": embedding,
            "confidence_floor": confidence_floor,
            "updated_at": now.isoformat(),
        }
        if content_blob_ref:
            update_fields["content_blob_ref"] = content_blob_ref
        if source_expedition:
            update_fields["source_expeditions"] = list(set(
                existing.get("source_expeditions", []) + [source_expedition]
            ))
        if findings_count is not None:
            update_fields["findings_count"] = findings_count

        collection.update_one({"uuid": priming_uuid}, {"$set": update_fields})
        action = "updated"
    else:
        doc = {
            "uuid": priming_uuid,
            "territory_name": territory_name,
            "territory_keys": keys_list,
            "territory_keys_text": keys_text,
            "content": content[:16000],
            "content_hash": content_hash,
            "embedding": embedding,
            "project": project,
            "project_uuid": str(project_uuid),
            "source_expeditions": [source_expedition] if source_expedition else [],
            "confidence_floor": confidence_floor,
            "findings_count": findings_count or {},
            "status": "active",
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
        }
        if content_blob_ref:
            doc["content_blob_ref"] = content_blob_ref
        collection.insert_one(doc)
        action = "inserted"

    emit_event(
        "expedition.priming.upserted",
        {
            "uuid": priming_uuid,
            "territory": territory_name,
            "action": action,
            "project": project,
        },
        db=db,
    )

    return {"action": action, "uuid": priming_uuid}


def get_priming_block(territory_name, project, project_uuid, db=None):
    """Retrieve a priming block by territory name.

    Args:
        territory_name: The territory label.
        project: Project display name.
        project_uuid: Project UUIDv8 (uuid.UUID).
        db: Optional database instance.

    Returns:
        Priming block document or None.
    """
    if db is None:
        db = get_database()

    collection = db[COLLECTION_PRIMING_REGISTRY]
    priming_uuid = _derive_priming_uuid(project_uuid, territory_name)
    return collection.find_one(
        {"uuid": priming_uuid},
        {"_id": 0, "embedding": 0},
    )


def find_relevant_priming(topic_text, project=None, limit=3, threshold=None, db=None):
    """Find priming blocks whose territory keys match a topic via vector search.

    This is the semantic activation mechanism: given a conversation topic,
    find priming blocks that should orient the session.

    Args:
        topic_text: Text describing the territory being entered.
        project: Optional project filter.
        limit: Max results.
        threshold: Minimum similarity (default from config).
        db: Optional database instance.

    Returns:
        List of priming block dicts with 'similarity' field.
    """
    if db is None:
        db = get_database()
    if threshold is None:
        threshold = PRIMING_TERRITORY_MATCH_THRESHOLD

    collection = db[COLLECTION_PRIMING_REGISTRY]
    embeddings = embed_texts([topic_text[:8000]])
    if not embeddings:
        return []
    embedding = embeddings[0]

    filter_clause = {"status": "active"}
    if project:
        filter_clause["project"] = project

    pipeline = [
        {
            "$vectorSearch": {
                "index": VECTOR_INDEX_NAME,
                "path": "embedding",
                "queryVector": embedding,
                "numCandidates": limit * 10,
                "limit": limit,
                "filter": filter_clause,
            }
        },
        {"$addFields": {"similarity": {"$meta": "vectorSearchScore"}}},
        {"$project": {"embedding": 0}},
    ]

    results = list(collection.aggregate(pipeline))
    return [r for r in results if r.get("similarity", 0) >= threshold]


def list_priming_blocks(project, db=None):
    """List all active priming blocks for a project.

    Args:
        project: Project display name.
        db: Optional database instance.

    Returns:
        List of priming block documents (without embeddings).
    """
    if db is None:
        db = get_database()

    collection = db[COLLECTION_PRIMING_REGISTRY]
    return list(
        collection.find(
            {"project": project, "status": "active"},
            {"_id": 0, "embedding": 0},
        ).sort("updated_at", -1)
    )


def deactivate_priming_block(priming_uuid, db=None):
    """Mark a priming block as inactive.

    Args:
        priming_uuid: The priming block's UUID string.
        db: Optional database instance.

    Returns:
        Dict with 'action' and 'uuid'.
    """
    if db is None:
        db = get_database()

    collection = db[COLLECTION_PRIMING_REGISTRY]
    now = datetime.now(timezone.utc)

    collection.update_one(
        {"uuid": priming_uuid},
        {"$set": {"status": "inactive", "updated_at": now.isoformat()}},
    )

    emit_event(
        "expedition.priming.deactivated",
        {"uuid": priming_uuid},
        db=db,
    )

    return {"action": "deactivated", "uuid": priming_uuid}
