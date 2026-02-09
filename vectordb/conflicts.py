"""Forge OS Layer 2: GRAPH — Two-signal conflict detection.

Detects conflicts between decisions using:
  Signal 1: Embedding similarity (cosine > threshold + different text_hash)
  Signal 2: Shared entity references with divergent epistemic tiers
"""

import re

from vectordb.config import (
    COLLECTION_DECISION_REGISTRY,
    DECISION_CONFLICT_SIMILARITY_THRESHOLD,
    EMBEDDING_DIMENSIONS,
    VECTOR_INDEX_NAME,
)
from vectordb.db import get_database
from vectordb.embeddings import embed_texts


_ENTITY_PATTERN = re.compile(r"[DT]\d{3,4}")
_PROJECT_KEYWORDS = re.compile(
    r"(?:Forge\s*OS|Reality\s*Compiler|Attention[\s-]*Currency|"
    r"Consciousness[\s-]*Physics|Wavelength|The\s*Nexus)",
    re.IGNORECASE,
)


def detect_conflicts(
    decision_text,
    decision_tier,
    project,
    exclude_uuid=None,
    db=None,
):
    """Detect potential conflicts between a decision and existing active decisions.

    Uses two independent signals:
      1. Embedding similarity above threshold with different text content
      2. Shared entity references (D-IDs, T-IDs, project names) with
         divergent epistemic tiers

    Args:
        decision_text: The text of the decision to check.
        decision_tier: Epistemic tier (float 0-1) of the new decision.
        project: Project display name.
        exclude_uuid: UUID to exclude from results (the decision itself).
        db: Optional database instance.

    Returns:
        List of conflict dicts with keys: existing_uuid, existing_text,
        signal, similarity, shared_entities, severity.
    """
    if db is None:
        db = get_database()

    conflicts = []
    seen_uuids = set()

    # Signal 1: Embedding similarity
    signal1_conflicts = _detect_by_similarity(
        decision_text, project, exclude_uuid, db
    )
    for conflict in signal1_conflicts:
        seen_uuids.add(conflict["existing_uuid"])
        conflicts.append(conflict)

    # Signal 2: Shared entities with tier divergence
    signal2_conflicts = _detect_by_entities(
        decision_text, decision_tier, project, exclude_uuid, seen_uuids, db
    )
    conflicts.extend(signal2_conflicts)

    return conflicts


def _detect_by_similarity(decision_text, project, exclude_uuid, db):
    """Signal 1: Find decisions with high embedding similarity but different text."""
    collection = db[COLLECTION_DECISION_REGISTRY]

    embeddings = embed_texts([decision_text[:8000]])
    if not embeddings:
        return []
    embedding = embeddings[0]

    pipeline = [
        {
            "$vectorSearch": {
                "index": VECTOR_INDEX_NAME,
                "path": "embedding",
                "queryVector": embedding,
                "numCandidates": 50,
                "limit": 10,
                "filter": {"project": project, "status": "active"},
            }
        },
        {"$addFields": {"similarity": {"$meta": "vectorSearchScore"}}},
        {"$project": {"embedding": 0}},
    ]

    results = list(collection.aggregate(pipeline))
    conflicts = []

    for doc in results:
        if doc.get("uuid") == exclude_uuid:
            continue
        similarity = doc.get("similarity", 0)
        if similarity < DECISION_CONFLICT_SIMILARITY_THRESHOLD:
            continue

        import hashlib
        new_hash = hashlib.sha256(
            decision_text.encode("utf-8")
        ).hexdigest()[:16]
        if doc.get("text_hash") == new_hash:
            continue

        severity = "high" if similarity > 0.92 else "medium"
        conflicts.append({
            "existing_uuid": doc["uuid"],
            "existing_text": doc.get("text", "")[:500],
            "signal": "embedding_similarity",
            "similarity": round(similarity, 4),
            "shared_entities": [],
            "severity": severity,
        })

    return conflicts


def _detect_by_entities(
    decision_text, decision_tier, project, exclude_uuid, already_flagged, db
):
    """Signal 2: Find decisions sharing entity references with tier divergence."""
    collection = db[COLLECTION_DECISION_REGISTRY]
    entities = _extract_entities(decision_text)
    if not entities:
        return []

    query = {
        "project": project,
        "status": "active",
    }
    if exclude_uuid:
        query["uuid"] = {"$ne": exclude_uuid}

    candidates = list(collection.find(query, {"_id": 0, "embedding": 0}))
    conflicts = []

    for doc in candidates:
        if doc["uuid"] in already_flagged:
            continue
        existing_entities = _extract_entities(doc.get("text", ""))
        shared = entities & existing_entities
        if not shared:
            continue

        existing_tier = doc.get("epistemic_tier")
        if existing_tier is None or decision_tier is None:
            continue
        if abs(existing_tier - decision_tier) < 0.2:
            continue

        severity = "high" if abs(existing_tier - decision_tier) > 0.4 else "medium"
        conflicts.append({
            "existing_uuid": doc["uuid"],
            "existing_text": doc.get("text", "")[:500],
            "signal": "entity_tier_divergence",
            "similarity": 0.0,
            "shared_entities": sorted(shared),
            "severity": severity,
        })

    return conflicts


def register_conflict(uuid_a, uuid_b, signal_type, db=None):
    """Record a conflict between two decisions via $addToSet.

    Args:
        uuid_a: First decision UUID string.
        uuid_b: Second decision UUID string.
        signal_type: "embedding_similarity" or "entity_tier_divergence".
        db: Optional database instance.
    """
    if db is None:
        db = get_database()

    collection = db[COLLECTION_DECISION_REGISTRY]

    collection.update_one(
        {"uuid": uuid_a},
        {"$addToSet": {"conflicts_with": uuid_b}},
    )
    collection.update_one(
        {"uuid": uuid_b},
        {"$addToSet": {"conflicts_with": uuid_a}},
    )


def _extract_entities(text):
    """Extract D-IDs, T-IDs, and project name references from text.

    Args:
        text: Input text to scan.

    Returns:
        Set of entity strings found.
    """
    entities = set()

    for match in _ENTITY_PATTERN.finditer(text):
        entities.add(match.group())

    for match in _PROJECT_KEYWORDS.finditer(text):
        entities.add(match.group().strip())

    return entities
