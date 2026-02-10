#!/usr/bin/env python3
"""CLI search tool for Claude conversations using MongoDB vector search."""

import argparse
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from vectordb.config import (
    COLLECTION_CODE_SESSIONS,
    COLLECTION_CONVERSATIONS,
    COLLECTION_MESSAGES,
    COLLECTION_PUBLISHED_ARTIFACTS,
    VECTOR_INDEX_NAME,
)
from vectordb.db import get_database
from vectordb.embeddings import embed_query, get_voyage_client


def vector_search(collection, query_embedding, limit, project_filter=None,
                  threshold=0.3, content_type=None, is_starred=None, model=None):
    """Run $vectorSearch aggregation pipeline with optional filters."""
    vector_search_stage = {
        "$vectorSearch": {
            "index": VECTOR_INDEX_NAME,
            "path": "embedding",
            "queryVector": query_embedding,
            "numCandidates": limit * 10,
            "limit": limit,
        }
    }

    # Build pre-filter for vector search (requires filter fields in index)
    vector_filter = {}
    if content_type:
        vector_filter["content_type"] = content_type
    if project_filter:
        vector_filter["project_name"] = project_filter
    if is_starred is not None:
        vector_filter["is_starred"] = is_starred

    if vector_filter:
        vector_search_stage["$vectorSearch"]["filter"] = vector_filter

    pipeline = [
        vector_search_stage,
        {"$addFields": {"score": {"$meta": "vectorSearchScore"}}},
        {"$match": {"score": {"$gte": threshold}}},
    ]

    # Post-filter for fields not in the vector index filter
    if model:
        pipeline.append({"$match": {"model": model}})

    # Drop embedding from results to keep output clean
    pipeline.append({"$project": {"embedding": 0}})

    return list(collection.aggregate(pipeline))


def print_conversation_results(results):
    """Format and print conversation search results."""
    if not results:
        print("  No conversation results found.")
        return

    for i, doc in enumerate(results, 1):
        score = doc.get("score", 0)
        name = doc.get("name", "(Untitled)")
        project = doc.get("project_name", "No Project")
        summary = doc.get("summary", "")
        model = doc.get("model", "")
        msg_count = doc.get("message_count", 0)
        content_type = doc.get("content_type", "")
        starred = doc.get("is_starred", False)

        star_indicator = " *" if starred else ""
        print(f"  {i}. [{score:.2f}] \"{name}\"{star_indicator} (Project: {project})")
        info_parts = []
        if model:
            info_parts.append(f"Model: {model}")
        info_parts.append(f"Messages: {msg_count}")
        if content_type:
            info_parts.append(f"Type: {content_type}")
        print(f"     {' | '.join(info_parts)}")
        if summary:
            display = summary[:200] + "..." if len(summary) > 200 else summary
            print(f"     {display}")
        print()


def print_message_results(results):
    """Format and print message search results."""
    if not results:
        print("  No message results found.")
        return

    for i, doc in enumerate(results, 1):
        score = doc.get("score", 0)
        sender = doc.get("sender", "unknown")
        conv_id = doc.get("conversation_id", "")[:8]
        project = doc.get("project_name", "No Project")
        msg_idx = doc.get("message_index", 0)
        text = doc.get("text", "")
        content_type = doc.get("content_type", "")

        display = text[:300] + "..." if len(text) > 300 else text
        # Replace newlines for compact display
        display = display.replace("\n", " ").strip()

        type_tag = f" [{content_type}]" if content_type else ""
        print(f"  {i}. [{score:.2f}] {sender} in conv {conv_id}...{type_tag} (msg #{msg_idx}, Project: {project})")
        print(f"     \"{display}\"")
        print()


def print_artifact_results(results):
    """Format and print published artifact search results."""
    if not results:
        print("  No artifact results found.")
        return

    for i, doc in enumerate(results, 1):
        score = doc.get("score", 0)
        title = doc.get("title", "(Untitled)")
        project = doc.get("project_name", "No Project")
        artifact_type = doc.get("artifact_type", "")
        language = doc.get("language", "")
        content_type = doc.get("content_type", "")
        content = doc.get("content", "")

        display = content[:200] + "..." if len(content) > 200 else content
        display = display.replace("\n", " ").strip()

        info_parts = []
        if artifact_type:
            info_parts.append(f"Type: {artifact_type}")
        if language:
            info_parts.append(f"Lang: {language}")
        if content_type:
            info_parts.append(f"Class: {content_type}")

        print(f"  {i}. [{score:.2f}] \"{title}\" (Project: {project})")
        if info_parts:
            print(f"     {' | '.join(info_parts)}")
        if display:
            print(f"     {display}")
        print()


def print_session_results(results):
    """Format and print Claude Code session search results."""
    if not results:
        print("  No session results found.")
        return

    for i, doc in enumerate(results, 1):
        score = doc.get("score", 0)
        title = doc.get("title", "(Untitled)")
        project = doc.get("project_name", "No Project")
        model = doc.get("model", "")
        status = doc.get("status", "")
        content_type = doc.get("content_type", "")
        summary = doc.get("summary", "")

        display = summary[:200] + "..." if len(summary) > 200 else summary
        display = display.replace("\n", " ").strip()

        info_parts = []
        if model:
            info_parts.append(f"Model: {model}")
        if status:
            info_parts.append(f"Status: {status}")
        if content_type:
            info_parts.append(f"Class: {content_type}")

        print(f"  {i}. [{score:.2f}] \"{title}\" (Project: {project})")
        if info_parts:
            print(f"     {' | '.join(info_parts)}")
        if display:
            print(f"     {display}")
        print()


def main():
    parser = argparse.ArgumentParser(
        description="Search Claude conversations using vector similarity"
    )
    parser.add_argument("query", help="Search query text")
    parser.add_argument(
        "--scope",
        choices=["messages", "conversations", "artifacts", "sessions", "both", "all"],
        default="both",
        help="Search scope: messages, conversations, artifacts, sessions, both (msgs+convs), all (default: both)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=5,
        help="Number of results per scope (default: 5)",
    )
    parser.add_argument(
        "--project",
        type=str,
        default=None,
        help="Filter by project name",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.3,
        help="Minimum similarity score 0-1 (default: 0.3)",
    )
    parser.add_argument(
        "--content-type",
        type=str,
        default=None,
        choices=[
            "conversation", "code_pattern", "error_recovery",
            "decision", "solution", "optimization", "routing",
        ],
        help="Filter by content type",
    )
    parser.add_argument(
        "--starred",
        action="store_true",
        default=False,
        help="Only show starred conversations/messages",
    )
    parser.add_argument(
        "--model",
        type=str,
        default=None,
        help="Filter by model name (e.g. claude-opus-4-6)",
    )

    args = parser.parse_args()

    db = get_database()
    voyage = get_voyage_client()

    print(f"Searching for: \"{args.query}\"")
    filters = []
    if args.project:
        filters.append(f"project={args.project}")
    if args.content_type:
        filters.append(f"type={args.content_type}")
    if args.starred:
        filters.append("starred=true")
    if args.model:
        filters.append(f"model={args.model}")
    if filters:
        print(f"Filters: {', '.join(filters)}")
    print()

    starred_filter = True if args.starred else None
    query_embedding = embed_query(args.query, client=voyage)

    if args.scope in ("conversations", "both", "all"):
        print("=== Conversation Results ===")
        conv_results = vector_search(
            db[COLLECTION_CONVERSATIONS],
            query_embedding,
            args.limit,
            project_filter=args.project,
            threshold=args.threshold,
            content_type=args.content_type,
            is_starred=starred_filter,
            model=args.model,
        )
        print_conversation_results(conv_results)

    if args.scope in ("messages", "both", "all"):
        print("=== Message Results ===")
        msg_results = vector_search(
            db[COLLECTION_MESSAGES],
            query_embedding,
            args.limit,
            project_filter=args.project,
            threshold=args.threshold,
            content_type=args.content_type,
            is_starred=starred_filter,
            model=args.model,
        )
        print_message_results(msg_results)

    if args.scope in ("artifacts", "all"):
        print("=== Published Artifact Results ===")
        artifact_results = vector_search(
            db[COLLECTION_PUBLISHED_ARTIFACTS],
            query_embedding,
            args.limit,
            project_filter=args.project,
            threshold=args.threshold,
            content_type=args.content_type,
        )
        print_artifact_results(artifact_results)

    if args.scope in ("sessions", "all"):
        print("=== Code Session Results ===")
        session_results = vector_search(
            db[COLLECTION_CODE_SESSIONS],
            query_embedding,
            args.limit,
            project_filter=args.project,
            threshold=args.threshold,
            content_type=args.content_type,
        )
        print_session_results(session_results)


if __name__ == "__main__":
    main()
