"""Forge OS Layer 2: GRAPH — Decision registry CRUD with auto-embedding.

Manages the lifecycle of decisions (D001, D002, ...) extracted from
compression archives. Decisions are content-addressed, auto-embedded
via VoyageAI, and conflict-checked on insert.
"""

import hashlib
from datetime import datetime, timedelta, timezone

from vectordb.config import (
    COLLECTION_DECISION_REGISTRY,
    DECISION_CONFLICT_SIMILARITY_THRESHOLD,
    EMBEDDING_DIMENSIONS,
    STALE_MAX_DAYS,
    STALE_MAX_HOPS,
    VECTOR_INDEX_NAME,
)
from vectordb.conflicts import detect_conflicts, register_conflict
from vectordb.db import get_database
from vectordb.display_ids import allocate_display_id, register_display_id
from vectordb.embeddings import embed_texts
from vectordb.blob_store import store as blob_store
from vectordb.events import emit_event
from vectordb.uuidv8 import decision_id as derive_decision_uuid


def upsert_decision(
    local_id,
    text,
    project,
    project_uuid,
    originated_conversation_id,
    epistemic_tier=None,
    status="active",
    dependents=None,
    dependencies=None,
    rationale=None,
    db=None,
):
    """Upsert a decision into the registry with auto-embedding.

    Three possible actions:
      - "validated": Same UUID + same text_hash -> update last_validated, reset hops
      - "updated": Same UUID + different text_hash -> re-embed, full upsert
      - "inserted": New UUID -> embed, run conflict detection

    Args:
        local_id: Archive-local identifier (e.g. "D001").
        text: Full decision text.
        project: Project display name.
        project_uuid: Project UUIDv8 (uuid.UUID).
        originated_conversation_id: UUID of originating conversation.
        epistemic_tier: Optional float 0-1 epistemic confidence.
        status: "active", "superseded", or "deprecated".
        dependents: Optional list of decision UUIDs that depend on this.
        dependencies: Optional list of decision local_ids this depends on.
        rationale: Optional rationale text.
        db: Optional database instance.

    Returns:
        Dict with 'action', 'uuid', 'conflicts' (if any).
    """
    if db is None:
        db = get_database()

    collection = db[COLLECTION_DECISION_REGISTRY]
    now = datetime.now(timezone.utc)

    decision_uuid = str(derive_decision_uuid(
        project_uuid, text, originated_conversation_id
    ))
    text_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]

    existing = collection.find_one({"uuid": decision_uuid})

    if existing is not None and existing.get("text_hash") == text_hash:
        return _validate_decision(collection, decision_uuid, now, db)

    if existing is not None:
        return _update_decision(
            collection, decision_uuid, local_id, text, text_hash,
            epistemic_tier, status, dependents, dependencies, rationale,
            now, db,
        )

    return _insert_decision(
        collection, decision_uuid, local_id, text, text_hash, project,
        project_uuid, originated_conversation_id, epistemic_tier, status,
        dependents, dependencies, rationale, now, db,
    )


def _validate_decision(collection, decision_uuid, now, db):
    """Same UUID + same text_hash: validate without re-embedding."""
    collection.update_one(
        {"uuid": decision_uuid},
        {
            "$set": {
                "last_validated": now,
                "hops_since_validated": 0,
                "updated_at": now.isoformat(),
            }
        },
    )

    emit_event(
        "graph.decision.validated",
        {"uuid": decision_uuid},
        db=db,
    )

    return {"action": "validated", "uuid": decision_uuid, "conflicts": []}


def _update_decision(
    collection, decision_uuid, local_id, text, text_hash,
    epistemic_tier, status, dependents, dependencies, rationale, now, db,
):
    """Same UUID + different text_hash: re-embed and update."""
    embeddings = embed_texts([text[:8000]])
    embedding = embeddings[0] if embeddings else [0.0] * EMBEDDING_DIMENSIONS

    text_blob_ref = blob_store(text)
    update_fields = {
        "local_id": local_id,
        "text": text[:8000],
        "text_hash": text_hash,
        "embedding": embedding,
        "status": status,
        "hops_since_validated": 0,
        "last_validated": now,
        "updated_at": now.isoformat(),
    }
    if text_blob_ref:
        update_fields["text_blob_ref"] = text_blob_ref
    if epistemic_tier is not None:
        update_fields["epistemic_tier"] = epistemic_tier
    if dependents is not None:
        update_fields["dependents"] = dependents
    if dependencies is not None:
        update_fields["dependencies"] = dependencies
    if rationale is not None:
        update_fields["rationale"] = rationale
        rationale_blob_ref = blob_store(rationale)
        if rationale_blob_ref:
            update_fields["rationale_blob_ref"] = rationale_blob_ref

    collection.update_one({"uuid": decision_uuid}, {"$set": update_fields})

    emit_event(
        "graph.decision.updated",
        {"uuid": decision_uuid, "text_hash": text_hash},
        db=db,
    )

    return {"action": "updated", "uuid": decision_uuid, "conflicts": []}


def _insert_decision(
    collection, decision_uuid, local_id, text, text_hash, project,
    project_uuid, originated_conversation_id, epistemic_tier, status,
    dependents, dependencies, rationale, now, db,
):
    """New UUID: embed, insert, and run conflict detection."""
    embeddings = embed_texts([text[:8000]])
    embedding = embeddings[0] if embeddings else [0.0] * EMBEDDING_DIMENSIONS

    text_blob_ref = blob_store(text)
    rationale_blob_ref = blob_store(rationale) if rationale else None

    display_id = allocate_display_id(project, "decision", db=db)

    doc = {
        "uuid": decision_uuid,
        "local_id": local_id,
        "global_display_id": display_id,
        "text": text[:8000],
        "text_hash": text_hash,
        "embedding": embedding,
        "project": project,
        "project_uuid": str(project_uuid),
        "originated_conversation": str(originated_conversation_id),
        "epistemic_tier": epistemic_tier,
        "status": status,
        "dependents": dependents or [],
        "dependencies": dependencies or [],
        "conflicts_with": [],
        "superseded_by": None,
        "rationale": rationale or "",
        "hops_since_validated": 0,
        "last_validated": now,
        "created_at": now.isoformat(),
        "updated_at": now.isoformat(),
    }
    if text_blob_ref:
        doc["text_blob_ref"] = text_blob_ref
    if rationale_blob_ref:
        doc["rationale_blob_ref"] = rationale_blob_ref

    collection.insert_one(doc)

    register_display_id(
        display_id, decision_uuid, COLLECTION_DECISION_REGISTRY, project, db=db,
    )

    # Run conflict detection against existing decisions
    conflicts = []
    try:
        conflicts = detect_conflicts(
            text, epistemic_tier, project,
            exclude_uuid=decision_uuid, db=db,
        )
        for conflict in conflicts:
            register_conflict(
                decision_uuid,
                conflict["existing_uuid"],
                conflict["signal"],
                db=db,
            )
    except Exception:
        # Conflict detection is best-effort; don't block insert
        pass

    emit_event(
        "graph.decision.inserted",
        {
            "uuid": decision_uuid,
            "local_id": local_id,
            "global_display_id": display_id,
            "project": project,
            "conflict_count": len(conflicts),
        },
        db=db,
    )

    return {
        "action": "inserted",
        "uuid": decision_uuid,
        "global_display_id": display_id,
        "conflicts": conflicts,
    }


def get_active_decisions(project, db=None):
    """Return all active decisions for a project.

    Args:
        project: Project display name.
        db: Optional database instance.

    Returns:
        List of decision documents (without embedding) sorted by
        epistemic_tier descending.
    """
    if db is None:
        db = get_database()

    collection = db[COLLECTION_DECISION_REGISTRY]
    results = list(
        collection.find(
            {"project": project, "status": "active"},
            {"_id": 0, "embedding": 0},
        )
    )

    results.sort(
        key=lambda d: d.get("epistemic_tier") or 0,
        reverse=True,
    )

    return results


def get_stale_decisions(project, max_hops=None, max_days=None, db=None):
    """Find decisions that haven't been validated recently.

    Args:
        project: Project display name.
        max_hops: Hop threshold (default from config).
        max_days: Day threshold (default from config).
        db: Optional database instance.

    Returns:
        List of stale decision documents.
    """
    if db is None:
        db = get_database()
    if max_hops is None:
        max_hops = STALE_MAX_HOPS
    if max_days is None:
        max_days = STALE_MAX_DAYS

    collection = db[COLLECTION_DECISION_REGISTRY]
    cutoff = datetime.now(timezone.utc) - timedelta(days=max_days)

    return list(
        collection.find(
            {
                "project": project,
                "status": "active",
                "$or": [
                    {"hops_since_validated": {"$gte": max_hops}},
                    {"last_validated": {"$lte": cutoff}},
                ],
            },
            {"_id": 0, "embedding": 0},
        )
    )


def supersede_decision(decision_uuid, superseded_by_uuid, db=None):
    """Mark a decision as superseded by another.

    Args:
        decision_uuid: The decision to supersede.
        superseded_by_uuid: The replacement decision's UUID.
        db: Optional database instance.

    Returns:
        Dict with 'action' and 'uuid'.
    """
    if db is None:
        db = get_database()

    collection = db[COLLECTION_DECISION_REGISTRY]
    now = datetime.now(timezone.utc)

    collection.update_one(
        {"uuid": decision_uuid},
        {
            "$set": {
                "status": "superseded",
                "superseded_by": superseded_by_uuid,
                "updated_at": now.isoformat(),
            }
        },
    )

    emit_event(
        "graph.decision.superseded",
        {
            "uuid": decision_uuid,
            "superseded_by": superseded_by_uuid,
        },
        db=db,
    )

    return {"action": "superseded", "uuid": decision_uuid}


def increment_decision_hops(project, exclude_uuids=None, db=None):
    """Increment hops_since_validated for active decisions NOT in exclude set.

    Args:
        project: Project display name.
        exclude_uuids: Set/list of decision UUIDs present in latest archive.
        db: Optional database instance.

    Returns:
        Number of decisions incremented.
    """
    if db is None:
        db = get_database()

    collection = db[COLLECTION_DECISION_REGISTRY]
    query = {
        "project": project,
        "status": "active",
    }
    if exclude_uuids:
        query["uuid"] = {"$nin": list(exclude_uuids)}

    result = collection.update_many(query, {"$inc": {"hops_since_validated": 1}})
    return result.modified_count


def find_similar_decisions(text, project, limit=5, threshold=None, db=None):
    """Find decisions similar to given text via vector search.

    Args:
        text: Query text.
        project: Project display name.
        limit: Max results.
        threshold: Minimum similarity score (default from config).
        db: Optional database instance.

    Returns:
        List of decision dicts with 'similarity' field.
    """
    if db is None:
        db = get_database()
    if threshold is None:
        threshold = DECISION_CONFLICT_SIMILARITY_THRESHOLD

    collection = db[COLLECTION_DECISION_REGISTRY]
    embeddings = embed_texts([text[:8000]])
    if not embeddings:
        return []
    embedding = embeddings[0]

    pipeline = [
        {
            "$vectorSearch": {
                "index": VECTOR_INDEX_NAME,
                "path": "embedding",
                "queryVector": embedding,
                "numCandidates": limit * 10,
                "limit": limit,
                "filter": {"project": project, "status": "active"},
            }
        },
        {"$addFields": {"similarity": {"$meta": "vectorSearchScore"}}},
        {"$project": {"embedding": 0}},
    ]

    results = list(collection.aggregate(pipeline))
    return [r for r in results if r.get("similarity", 0) >= threshold]
