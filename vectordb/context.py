"""Forge OS Layer 1: MEMORY — context assembly functions."""

from vectordb.config import (
    COLLECTION_CONVERSATIONS,
    COLLECTION_MESSAGES,
    COLLECTION_PATTERNS,
    VECTOR_INDEX_NAME,
)
from vectordb.db import get_database
from vectordb.embeddings import embed_query


def context_load(query, project_name=None, max_messages=10, max_patterns=3,
                 max_conversations=3, db=None):
    """Assemble execution context from all memory collections.

    Gathers relevant messages, patterns, and conversation summaries into
    a single context object suitable for injection into a prompt.

    Args:
        query: The query/task to build context for.
        project_name: Optional project filter.
        max_messages: Max message results.
        max_patterns: Max pattern results.
        max_conversations: Max conversation summary results.
        db: Optional database instance.

    Returns:
        Dict with 'messages', 'patterns', 'conversations', and 'context_text' keys.
    """
    if db is None:
        db = get_database()

    query_embedding = embed_query(query)

    messages = _search_collection(
        db, COLLECTION_MESSAGES, query_embedding, max_messages,
        project_name=project_name,
    )
    patterns = _search_collection(
        db, COLLECTION_PATTERNS, query_embedding, max_patterns,
    )
    conversations = _search_collection(
        db, COLLECTION_CONVERSATIONS, query_embedding, max_conversations,
        project_name=project_name,
    )

    context_text = _assemble_context_text(messages, patterns, conversations)

    return {
        "messages": messages,
        "patterns": patterns,
        "conversations": conversations,
        "context_text": context_text,
    }


def _search_collection(db, collection_name, query_embedding, limit,
                       project_name=None):
    """Run $vectorSearch on a collection with optional project filter."""
    vector_search_stage = {
        "$vectorSearch": {
            "index": VECTOR_INDEX_NAME,
            "path": "embedding",
            "queryVector": query_embedding,
            "numCandidates": limit * 10,
            "limit": limit,
        }
    }

    if project_name:
        if collection_name == COLLECTION_PATTERNS:
            pass  # Patterns don't have project_name as a filter field
        else:
            vector_search_stage["$vectorSearch"]["filter"] = {
                "project_name": project_name,
            }

    pipeline = [
        vector_search_stage,
        {"$addFields": {"score": {"$meta": "vectorSearchScore"}}},
        {"$match": {"score": {"$gte": 0.3}}},
        {"$project": {"embedding": 0}},
    ]

    return list(db[collection_name].aggregate(pipeline))


def _assemble_context_text(messages, patterns, conversations):
    """Build a single context string from all retrieved memory."""
    parts = []

    if conversations:
        parts.append("## Relevant Conversations")
        for conv in conversations:
            name = conv.get("name", "(Untitled)")
            summary = conv.get("summary", "")
            project = conv.get("project_name", "")
            score = conv.get("score", 0)
            parts.append(
                f"- [{score:.2f}] \"{name}\" (Project: {project})\n  {summary[:300]}"
            )

    if patterns:
        parts.append("\n## Relevant Patterns")
        for pat in patterns:
            content = pat.get("content", "")
            ptype = pat.get("pattern_type", "")
            score = pat.get("score", pat.get("success_score", 0))
            parts.append(f"- [{ptype}] (score: {score:.2f}) {content[:300]}")

    if messages:
        parts.append("\n## Relevant Messages")
        for msg in messages:
            sender = msg.get("sender", "unknown")
            text = msg.get("text", "")
            score = msg.get("score", 0)
            parts.append(f"- [{score:.2f}] {sender}: {text[:200]}")

    return "\n".join(parts) if parts else ""


def context_flush(context_id=None, db=None):
    """Clear assembled context from the scratchpad.

    This is a convenience wrapper that clears scratchpad entries
    associated with a context session.

    Args:
        context_id: The context/session ID to flush. If None, no-op.
        db: Optional database instance.

    Returns:
        Number of scratchpad entries cleared, or 0 if no context_id.
    """
    if not context_id:
        return 0

    from vectordb.scratchpad import scratchpad_clear
    return scratchpad_clear(context_id, db=db)


def context_resize(context_text, max_chars=4000):
    """Truncate assembled context to fit within a character budget.

    Preserves section headers and trims from the end of each section.

    Args:
        context_text: The full context string from context_load().
        max_chars: Maximum character count.

    Returns:
        Truncated context string.
    """
    if not context_text or len(context_text) <= max_chars:
        return context_text or ""

    # Split into sections and trim proportionally
    sections = context_text.split("\n## ")
    if len(sections) <= 1:
        return context_text[:max_chars]

    budget_per_section = max_chars // len(sections)
    trimmed = []
    for i, section in enumerate(sections):
        prefix = "" if i == 0 else "\n## "
        if len(section) > budget_per_section:
            trimmed.append(f"{prefix}{section[:budget_per_section]}...")
        else:
            trimmed.append(f"{prefix}{section}")

    result = "".join(trimmed)
    return result[:max_chars]
