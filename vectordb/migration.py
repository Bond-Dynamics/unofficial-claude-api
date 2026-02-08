"""Forge OS Layer 1: MEMORY — one-time migration to enrich existing data.

Enriches 3,777 messages and 222 conversations with content_type + metadata,
embeds project docs into document_embeddings, and rebuilds vector indexes.

Run with: python3 -m vectordb.migration
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from vectordb.chunker import chunk_text
from vectordb.classifier import classify_content
from vectordb.config import (
    COLLECTION_CONVERSATIONS,
    COLLECTION_DOCUMENTS,
    COLLECTION_MESSAGES,
    EMBEDDING_DIMENSIONS,
)
from vectordb.db import ensure_forge_indexes, ensure_indexes, get_database
from vectordb.embeddings import embed_texts, get_voyage_client
from vectordb.events import emit_event

DATA_DIR = Path(__file__).parent.parent / "data"
CONVERSATIONS_DIR = DATA_DIR / "conversations"
PROJECTS_DIR = DATA_DIR / "projects"


def _load_json(path):
    """Load a JSON file, returning None on error."""
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError) as err:
        print(f"  Skipping {path.name}: {err}")
        return None


def _build_conversation_lookup():
    """Build a lookup from conversation UUID to conversation JSON data."""
    lookup = {}
    if not CONVERSATIONS_DIR.exists():
        return lookup

    for path in CONVERSATIONS_DIR.glob("*.json"):
        conv = _load_json(path)
        if conv and conv.get("uuid"):
            lookup[conv["uuid"]] = conv

    return lookup


def _build_project_lookup():
    """Build a lookup from project UUID to project JSON data."""
    lookup = {}
    if not PROJECTS_DIR.exists():
        return lookup

    for path in PROJECTS_DIR.glob("*.json"):
        project = _load_json(path)
        if project and project.get("uuid"):
            lookup[project["uuid"]] = project

    return lookup


def _enrich_messages(db, conv_lookup):
    """Enrich existing message_embeddings with content_type and metadata.

    No re-embedding — only adds new fields from source conversation JSONs.
    """
    collection = db[COLLECTION_MESSAGES]
    cursor = collection.find(
        {"content_type": {"$exists": False}},
        {"_id": 1, "conversation_id": 1, "text": 1, "message_index": 1},
    )

    enriched = 0
    for doc in cursor:
        conv_id = doc.get("conversation_id", "")
        conv_data = conv_lookup.get(conv_id, {})
        messages = conv_data.get("chat_messages", [])
        msg_index = doc.get("message_index", 0)

        # Find the source message for metadata extraction
        source_msg = {}
        if msg_index < len(messages):
            source_msg = messages[msg_index]

        content_type = classify_content(doc.get("text", ""))
        project_uuid = conv_data.get("project_uuid", "")

        metadata = {
            "model": conv_data.get("model", ""),
            "has_attachments": bool(source_msg.get("attachments")),
            "has_sync_sources": bool(source_msg.get("sync_sources")),
            "is_starred": conv_data.get("is_starred", False),
            "parent_message_uuid": source_msg.get("parent_message_uuid", ""),
            "input_mode": source_msg.get("input_mode", ""),
        }

        message_uuid = source_msg.get("uuid", "")

        update = {
            "$set": {
                "content_type": content_type,
                "metadata": metadata,
                "message_uuid": message_uuid,
                "project_uuid": project_uuid,
            }
        }

        collection.update_one({"_id": doc["_id"]}, update)
        enriched += 1

    return enriched


def _enrich_conversations(db, conv_lookup):
    """Enrich existing conversation_embeddings with content_type and metadata."""
    collection = db[COLLECTION_CONVERSATIONS]
    cursor = collection.find(
        {"content_type": {"$exists": False}},
        {"_id": 1, "conversation_id": 1, "summary": 1, "name": 1},
    )

    enriched = 0
    for doc in cursor:
        conv_id = doc.get("conversation_id", "")
        conv_data = conv_lookup.get(conv_id, {})

        text_for_classify = f"{doc.get('name', '')} {doc.get('summary', '')}"
        content_type = classify_content(text_for_classify)

        messages = conv_data.get("chat_messages", [])
        human_count = sum(1 for m in messages if m.get("sender") == "human")
        assistant_count = sum(1 for m in messages if m.get("sender") == "assistant")
        attachment_count = sum(
            len(m.get("attachments", [])) for m in messages
        )

        metadata = {
            "settings": conv_data.get("settings", {}),
            "has_attachments": attachment_count > 0,
            "has_sync_sources": any(
                bool(m.get("sync_sources")) for m in messages
            ),
            "attachment_count": attachment_count,
            "human_message_count": human_count,
            "assistant_message_count": assistant_count,
        }

        update = {
            "$set": {
                "content_type": content_type,
                "metadata": metadata,
                "project_uuid": conv_data.get("project_uuid", ""),
                "is_starred": conv_data.get("is_starred", False),
                "platform": conv_data.get("platform", ""),
            }
        }

        collection.update_one({"_id": doc["_id"]}, update)
        enriched += 1

    return enriched


def _embed_project_docs(db, project_lookup, voyage):
    """Chunk and embed project knowledge docs into document_embeddings."""
    collection = db[COLLECTION_DOCUMENTS]
    total_chunks = 0

    for project_uuid, project in project_lookup.items():
        # Build document text from project description + prompt_template + docs
        parts = []
        name = project.get("name", "")
        desc = project.get("description", "")
        prompt = project.get("prompt_template", "")

        if desc:
            parts.append(f"# {name}\n\n{desc}")
        if prompt:
            parts.append(f"## Prompt Template\n\n{prompt}")

        for doc_item in project.get("docs", []):
            doc_content = doc_item.get("content", "")
            doc_name = doc_item.get("filename", doc_item.get("name", ""))
            if doc_content:
                parts.append(f"## {doc_name}\n\n{doc_content}")

        full_text = "\n\n".join(parts)
        if not full_text or len(full_text.strip()) < 20:
            continue

        # Skip if already embedded for this project
        existing = collection.find_one({"project_uuid": project_uuid, "source_type": "project_doc"})
        if existing:
            continue

        chunks = chunk_text(full_text, chunk_size=1000, overlap=200)
        if not chunks:
            continue

        # Embed all chunks in a batch
        chunk_texts = [c["chunk_text"][:8000] for c in chunks]
        embeddings = embed_texts(chunk_texts, client=voyage)

        docs_to_insert = []
        for chunk_data, embedding in zip(chunks, embeddings):
            content_type = classify_content(chunk_data["chunk_text"])
            docs_to_insert.append({
                "source_type": "project_doc",
                "source_id": project_uuid,
                "project_name": name,
                "project_uuid": project_uuid,
                "title": name,
                "chunk_text": chunk_data["chunk_text"][:2000],
                "chunk_index": chunk_data["chunk_index"],
                "total_chunks": chunk_data["total_chunks"],
                "embedding": embedding,
                "content_type": content_type,
                "metadata": {
                    "file_type": "project_json",
                    "is_starred": project.get("is_starred", False),
                },
                "created_at": datetime.now(timezone.utc).isoformat(),
            })

        if docs_to_insert:
            collection.insert_many(docs_to_insert)
            total_chunks += len(docs_to_insert)
            print(f"  Embedded project: {name} ({len(docs_to_insert)} chunks)")

    return total_chunks


def run_migration():
    """Execute the full Forge OS Layer 1 migration.

    1. Build lookups from source JSON files
    2. Enrich messages with content_type + metadata
    3. Enrich conversations with content_type + metadata
    4. Embed project docs into document_embeddings
    5. Rebuild all indexes with filter fields
    6. Create new collections (patterns, scratchpad, archive, events)
    """
    print("=" * 60)
    print("Forge OS Layer 1: MEMORY — Schema Evolution Migration")
    print("=" * 60)

    db = get_database()

    # Step 1: Build lookups
    print("\n[1/6] Building conversation lookup from JSON files...")
    conv_lookup = _build_conversation_lookup()
    print(f"  Loaded {len(conv_lookup)} conversations from disk")

    print("\n[2/6] Building project lookup from JSON files...")
    project_lookup = _build_project_lookup()
    print(f"  Loaded {len(project_lookup)} projects from disk")

    # Step 2: Enrich messages
    print("\n[3/6] Enriching messages with content_type + metadata...")
    msg_count = _enrich_messages(db, conv_lookup)
    print(f"  Enriched {msg_count} messages")

    # Step 3: Enrich conversations
    print("\n[4/6] Enriching conversations with content_type + metadata...")
    conv_count = _enrich_conversations(db, conv_lookup)
    print(f"  Enriched {conv_count} conversations")

    # Step 4: Embed project docs
    print("\n[5/6] Embedding project docs into document_embeddings...")
    try:
        voyage = get_voyage_client()
        chunk_count = _embed_project_docs(db, project_lookup, voyage)
        print(f"  Embedded {chunk_count} total chunks from project docs")
    except RuntimeError as err:
        print(f"  Skipping project doc embedding: {err}")
        chunk_count = 0

    # Step 5+6: Rebuild indexes and create new collections
    print("\n[6/6] Rebuilding indexes with filter fields + creating new collections...")
    ensure_forge_indexes(db)
    print("  Indexes rebuilt successfully")

    # Log migration event
    emit_event(
        "memory.migration.completed",
        {
            "messages_enriched": msg_count,
            "conversations_enriched": conv_count,
            "project_chunks_embedded": chunk_count,
            "conversations_on_disk": len(conv_lookup),
            "projects_on_disk": len(project_lookup),
        },
        db=db,
    )

    print("\n" + "=" * 60)
    print("Migration complete!")
    print(f"  Messages enriched:        {msg_count}")
    print(f"  Conversations enriched:   {conv_count}")
    print(f"  Project doc chunks:       {chunk_count}")
    print(f"  New collections created:  patterns, scratchpad, archive, memory_events")
    print("=" * 60)


if __name__ == "__main__":
    run_migration()
