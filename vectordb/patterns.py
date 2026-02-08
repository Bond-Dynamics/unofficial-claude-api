"""Forge OS Layer 1: MEMORY — pattern_store() and pattern_match() functions."""

import uuid
from datetime import datetime, timezone

from vectordb.config import (
    COLLECTION_PATTERNS,
    EMBEDDING_DIMENSIONS,
    PATTERN_CONFIDENCE_SCORE_WEIGHT,
    PATTERN_CONFIDENCE_SIMILARITY_WEIGHT,
    PATTERN_DEFAULT_LIMIT,
    PATTERN_MERGE_THRESHOLD,
    VECTOR_INDEX_NAME,
)
from vectordb.db import get_database
from vectordb.embeddings import embed_query, embed_texts
from vectordb.events import emit_event


def pattern_store(content, pattern_type, success_score, tags=None,
                  source_conversation_id=None, source_project_name=None,
                  metadata=None, db=None):
    """Store or merge a pattern in the pattern store.

    If a pattern with >0.9 similarity already exists, merges via
    weighted average of success_score and increments merge_count.
    Otherwise inserts a new pattern.

    Args:
        content: Pattern content text.
        pattern_type: One of 'routing', 'execution', 'error_recovery', 'optimization'.
        success_score: Float 0-1 indicating how successful this pattern was.
        tags: Optional list of tag strings.
        source_conversation_id: Optional conversation ID where pattern was learned.
        source_project_name: Optional project name.
        metadata: Optional dict of additional metadata.
        db: Optional database instance.

    Returns:
        Dict with 'action' ('inserted' or 'merged') and the pattern document.
    """
    if db is None:
        db = get_database()

    collection = db[COLLECTION_PATTERNS]
    embeddings = embed_texts([content[:8000]])
    embedding = embeddings[0] if embeddings else [0.0] * EMBEDDING_DIMENSIONS

    # Search for existing similar pattern
    existing = _find_similar_pattern(collection, embedding, pattern_type)

    if existing and existing.get("score", 0) >= PATTERN_MERGE_THRESHOLD:
        return _merge_pattern(collection, existing, success_score, content, db)

    return _insert_pattern(
        collection, content, embedding, pattern_type, success_score,
        tags, source_conversation_id, source_project_name, metadata, db,
    )


def _find_similar_pattern(collection, embedding, pattern_type):
    """Search for an existing pattern with high similarity."""
    vector_search_stage = {
        "$vectorSearch": {
            "index": VECTOR_INDEX_NAME,
            "path": "embedding",
            "queryVector": embedding,
            "numCandidates": 20,
            "limit": 1,
            "filter": {"pattern_type": pattern_type},
        }
    }

    pipeline = [
        vector_search_stage,
        {"$addFields": {"score": {"$meta": "vectorSearchScore"}}},
    ]

    results = list(collection.aggregate(pipeline))
    return results[0] if results else None


def _merge_pattern(collection, existing, new_score, new_content, db):
    """Merge a new pattern into an existing one via weighted average."""
    old_score = existing.get("success_score", 0.5)
    merge_count = existing.get("metadata", {}).get("merge_count", 1)

    # Weighted average: existing weight = merge_count, new weight = 1
    merged_score = ((old_score * merge_count) + new_score) / (merge_count + 1)
    now = datetime.now(timezone.utc)

    update = {
        "$set": {
            "success_score": round(merged_score, 4),
            "last_used": now,
            "updated_at": now.isoformat(),
        },
        "$inc": {"metadata.merge_count": 1},
    }

    collection.update_one({"_id": existing["_id"]}, update)

    emit_event(
        "memory.pattern.merged",
        {
            "pattern_id": existing.get("pattern_id"),
            "old_score": old_score,
            "new_score": round(merged_score, 4),
            "merge_count": merge_count + 1,
        },
        db=db,
    )

    return {
        "action": "merged",
        "pattern_id": existing.get("pattern_id"),
        "success_score": round(merged_score, 4),
        "merge_count": merge_count + 1,
    }


def _insert_pattern(collection, content, embedding, pattern_type, success_score,
                    tags, source_conversation_id, source_project_name, metadata, db):
    """Insert a new pattern document."""
    now = datetime.now(timezone.utc)
    pattern_id = f"pat_{uuid.uuid4().hex[:12]}"

    doc = {
        "pattern_id": pattern_id,
        "pattern_type": pattern_type,
        "content": content[:4000],
        "embedding": embedding,
        "success_score": round(success_score, 4),
        "retrieval_count": 0,
        "last_used": now,
        "tags": tags or [],
        "source_conversation_id": source_conversation_id,
        "source_project_name": source_project_name,
        "metadata": {
            "merge_count": 1,
            **(metadata or {}),
        },
        "created_at": now.isoformat(),
        "updated_at": now.isoformat(),
    }

    collection.insert_one(doc)

    emit_event(
        "memory.pattern.stored",
        {
            "pattern_id": pattern_id,
            "pattern_type": pattern_type,
            "success_score": success_score,
        },
        db=db,
    )

    return {
        "action": "inserted",
        "pattern_id": pattern_id,
        "success_score": round(success_score, 4),
    }


def pattern_match(query, pattern_type=None, limit=None, db=None):
    """Find matching patterns by semantic similarity + success score.

    Confidence = (similarity * 0.6) + (success_score * 0.4)

    Args:
        query: Search query text.
        pattern_type: Optional filter by pattern type.
        limit: Max results (default from config).
        db: Optional database instance.

    Returns:
        List of pattern dicts with 'confidence' and 'similarity' fields,
        sorted by confidence descending.
    """
    if db is None:
        db = get_database()

    if limit is None:
        limit = PATTERN_DEFAULT_LIMIT

    collection = db[COLLECTION_PATTERNS]
    query_embedding = embed_query(query)

    vector_search_stage = {
        "$vectorSearch": {
            "index": VECTOR_INDEX_NAME,
            "path": "embedding",
            "queryVector": query_embedding,
            "numCandidates": limit * 10,
            "limit": limit,
        }
    }

    if pattern_type:
        vector_search_stage["$vectorSearch"]["filter"] = {
            "pattern_type": pattern_type,
        }

    pipeline = [
        vector_search_stage,
        {"$addFields": {"similarity": {"$meta": "vectorSearchScore"}}},
        {"$project": {"embedding": 0}},
    ]

    results = list(collection.aggregate(pipeline))

    # Compute confidence and sort
    for doc in results:
        similarity = doc.get("similarity", 0)
        score = doc.get("success_score", 0.5)
        doc["confidence"] = round(
            (similarity * PATTERN_CONFIDENCE_SIMILARITY_WEIGHT)
            + (score * PATTERN_CONFIDENCE_SCORE_WEIGHT),
            4,
        )

    results.sort(key=lambda d: d["confidence"], reverse=True)

    # Increment retrieval_count on returned patterns
    if results:
        pattern_ids = [d["pattern_id"] for d in results if "pattern_id" in d]
        if pattern_ids:
            collection.update_many(
                {"pattern_id": {"$in": pattern_ids}},
                {
                    "$inc": {"retrieval_count": 1},
                    "$set": {"last_used": datetime.now(timezone.utc)},
                },
            )

        emit_event(
            "memory.pattern.matched",
            {
                "query_preview": query[:100],
                "result_count": len(results),
                "top_confidence": results[0]["confidence"],
            },
            db=db,
        )

    return results
