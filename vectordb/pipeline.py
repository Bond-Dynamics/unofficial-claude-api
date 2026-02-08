"""Embed Claude conversations from data/conversations/ into MongoDB."""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from vectordb.classifier import classify_content
from vectordb.config import COLLECTION_CONVERSATIONS, COLLECTION_MESSAGES
from vectordb.db import ensure_forge_indexes, get_database
from vectordb.embeddings import embed_texts, get_voyage_client
from vectordb.events import emit_event

DATA_DIR = Path(__file__).parent.parent / "data"
CONVERSATIONS_DIR = DATA_DIR / "conversations"


def _extract_message_text(msg):
    """Extract plain text from a chat message."""
    # Claude API uses "text" field directly
    text = msg.get("text")
    if text:
        return text

    # Fallback: some formats use "content" with blocks
    content = msg.get("content", [])
    if isinstance(content, str):
        return content

    parts = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "text":
            parts.append(block["text"])
        elif isinstance(block, str):
            parts.append(block)
    return "\n".join(parts)


def _load_conversation(path):
    """Load a conversation JSON file."""
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError) as err:
        print(f"  Skipping {path.name}: {err}")
        return None


def run_pipeline():
    """Main embedding pipeline: reads conversations, embeds, stores in MongoDB."""
    if not CONVERSATIONS_DIR.exists():
        print(f"No conversations directory found at {CONVERSATIONS_DIR}")
        print("Run fetch_conversations.py first.")
        return

    conversation_files = sorted(CONVERSATIONS_DIR.glob("*.json"))
    if not conversation_files:
        print("No conversation files found.")
        return

    print(f"Found {len(conversation_files)} conversation files")

    db = get_database()
    print("Ensuring indexes...")
    collections = ensure_forge_indexes(db)
    msg_col = collections["messages"]
    conv_col = collections["conversations"]

    voyage = get_voyage_client()

    stats = {"conversations_embedded": 0, "messages_embedded": 0, "skipped": 0}

    for i, filepath in enumerate(conversation_files):
        conv = _load_conversation(filepath)
        if conv is None:
            continue

        conv_id = conv.get("uuid", "")
        conv_name = conv.get("name") or "(Untitled)"
        updated_at = conv.get("updated_at", "")
        progress = f"[{i + 1}/{len(conversation_files)}]"

        # Skip if already embedded with same updated_at
        existing = conv_col.find_one(
            {"conversation_id": conv_id},
            {"updated_at": 1},
        )
        if existing and existing.get("updated_at") == updated_at:
            stats["skipped"] += 1
            continue

        messages = conv.get("chat_messages", [])
        project_name = conv.get("project_name", "No Project")
        model = conv.get("model", "unknown")

        # Build message texts for embedding
        msg_texts = []
        msg_records = []
        for idx, msg in enumerate(messages):
            sender = msg.get("sender", "unknown")
            text = _extract_message_text(msg)
            if not text or len(text.strip()) < 10:
                continue

            # Truncate very long messages for embedding (VoyageAI has token limits)
            embed_text = text[:8000]
            content_type = classify_content(text)
            msg_records.append({
                "conversation_id": conv_id,
                "message_index": idx,
                "sender": sender,
                "text": text[:2000],  # Store truncated for display
                "project_name": project_name,
                "created_at": msg.get("created_at", ""),
                "message_uuid": msg.get("uuid", ""),
                "project_uuid": conv.get("project_uuid", ""),
                "content_type": content_type,
                "metadata": {
                    "model": model,
                    "has_attachments": bool(msg.get("attachments")),
                    "has_sync_sources": bool(msg.get("sync_sources")),
                    "is_starred": conv.get("is_starred", False),
                    "parent_message_uuid": msg.get("parent_message_uuid", ""),
                    "input_mode": msg.get("input_mode", ""),
                },
            })
            msg_texts.append(embed_text)

        # Embed messages in batches
        if msg_texts:
            msg_embeddings = embed_texts(msg_texts, client=voyage)

            # Remove old messages for this conversation, then insert fresh
            msg_col.delete_many({"conversation_id": conv_id})

            docs_to_insert = []
            for record, embedding in zip(msg_records, msg_embeddings):
                docs_to_insert.append({**record, "embedding": embedding})

            if docs_to_insert:
                msg_col.insert_many(docs_to_insert)
                stats["messages_embedded"] += len(docs_to_insert)

        # Embed conversation summary
        summary_parts = [conv_name]
        if conv.get("summary"):
            summary_parts.append(conv["summary"])
        summary_text = " - ".join(summary_parts)

        if len(summary_text.strip()) >= 5:
            conv_embeddings = embed_texts([summary_text[:4000]], client=voyage)

            conv_content_type = classify_content(summary_text)
            human_count = sum(1 for m in messages if m.get("sender") == "human")
            assistant_count = sum(1 for m in messages if m.get("sender") == "assistant")
            attachment_count = sum(len(m.get("attachments", [])) for m in messages)

            conv_col.update_one(
                {"conversation_id": conv_id},
                {
                    "$set": {
                        "conversation_id": conv_id,
                        "name": conv_name,
                        "summary": conv.get("summary", ""),
                        "embedding": conv_embeddings[0],
                        "message_count": len(messages),
                        "model": model,
                        "project_name": project_name,
                        "created_at": conv.get("created_at", ""),
                        "updated_at": updated_at,
                        "project_uuid": conv.get("project_uuid", ""),
                        "is_starred": conv.get("is_starred", False),
                        "platform": conv.get("platform", ""),
                        "content_type": conv_content_type,
                        "metadata": {
                            "settings": conv.get("settings", {}),
                            "has_attachments": attachment_count > 0,
                            "has_sync_sources": any(
                                bool(m.get("sync_sources")) for m in messages
                            ),
                            "attachment_count": attachment_count,
                            "human_message_count": human_count,
                            "assistant_message_count": assistant_count,
                        },
                    }
                },
                upsert=True,
            )
            stats["conversations_embedded"] += 1

        print(f"  {progress} Embedded: {conv_name} ({len(msg_texts)} msgs)")

    emit_event(
        "memory.pipeline.completed",
        {
            "conversations_embedded": stats["conversations_embedded"],
            "messages_embedded": stats["messages_embedded"],
            "skipped": stats["skipped"],
        },
        db=db,
    )

    print(f"\nPipeline complete!")
    print(f"  Conversations embedded: {stats['conversations_embedded']}")
    print(f"  Messages embedded:      {stats['messages_embedded']}")
    print(f"  Skipped (unchanged):    {stats['skipped']}")


if __name__ == "__main__":
    run_pipeline()
