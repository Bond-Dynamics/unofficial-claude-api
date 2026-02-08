"""Forge OS Layer 1: MEMORY — vector_store() and vector_search() functions."""

from datetime import datetime, timezone

from vectordb.classifier import classify_content
from vectordb.config import (
    COLLECTION_MESSAGES,
    EMBEDDING_DIMENSIONS,
    VECTOR_INDEX_NAME,
)
from vectordb.db import get_database
from vectordb.embeddings import embed_query, embed_texts
from vectordb.events import emit_event


def vector_store(text, collection_name=COLLECTION_MESSAGES, metadata=None,
                 embedding=None, db=None):
    """Store a document with its embedding in a collection.

    If no embedding is provided, the text is embedded via VoyageAI.
    Content type is auto-classified from the text.

    Args:
        text: The text content to store.
        collection_name: Target collection name.
        metadata: Optional dict of additional fields to store alongside.
        embedding: Pre-computed embedding vector. If None, text is embedded.
        db: Optional database instance.

    Returns:
        The inserted document (without the embedding, for readability).
    """
    if db is None:
        db = get_database()

    if embedding is None:
        embeddings = embed_texts([text[:8000]])
        embedding = embeddings[0] if embeddings else [0.0] * EMBEDDING_DIMENSIONS

    content_type = classify_content(text)
    now = datetime.now(timezone.utc)

    doc = {
        "text": text[:2000],
        "embedding": embedding,
        "content_type": content_type,
        "created_at": now.isoformat(),
        "updated_at": now.isoformat(),
    }

    if metadata:
        doc.update(metadata)

    result = db[collection_name].insert_one(doc)

    emit_event(
        "memory.vector.stored",
        {
            "collection": collection_name,
            "document_id": str(result.inserted_id),
            "content_type": content_type,
        },
        db=db,
    )

    return {k: v for k, v in doc.items() if k != "embedding"}


def vector_search(query, collection_name=COLLECTION_MESSAGES, limit=5,
                  content_type=None, sender=None, project_name=None,
                  is_starred=None, threshold=0.3, db=None):
    """Semantic vector search with optional metadata filters.

    Args:
        query: Search query text (will be embedded).
        collection_name: Collection to search.
        limit: Max results to return.
        content_type: Optional content_type filter.
        sender: Optional sender filter (messages only).
        project_name: Optional project_name filter.
        is_starred: Optional starred filter (bool).
        threshold: Minimum similarity score (0-1).
        db: Optional database instance.

    Returns:
        List of matching documents with 'score' field, sorted by score desc.
    """
    if db is None:
        db = get_database()

    query_embedding = embed_query(query)

    # Build filter for $vectorSearch
    vector_filter = {}
    if content_type:
        vector_filter["content_type"] = content_type
    if sender:
        vector_filter["sender"] = sender
    if project_name:
        vector_filter["project_name"] = project_name
    if is_starred is not None:
        # Support both top-level and nested metadata paths
        vector_filter["is_starred"] = is_starred

    vector_search_stage = {
        "$vectorSearch": {
            "index": VECTOR_INDEX_NAME,
            "path": "embedding",
            "queryVector": query_embedding,
            "numCandidates": limit * 10,
            "limit": limit,
        }
    }

    if vector_filter:
        vector_search_stage["$vectorSearch"]["filter"] = vector_filter

    pipeline = [
        vector_search_stage,
        {"$addFields": {"score": {"$meta": "vectorSearchScore"}}},
        {"$match": {"score": {"$gte": threshold}}},
        {"$project": {"embedding": 0}},
    ]

    results = list(db[collection_name].aggregate(pipeline))

    if results:
        emit_event(
            "memory.vector.searched",
            {
                "collection": collection_name,
                "query_preview": query[:100],
                "result_count": len(results),
                "top_score": results[0].get("score", 0) if results else 0,
            },
            db=db,
        )

    return results
