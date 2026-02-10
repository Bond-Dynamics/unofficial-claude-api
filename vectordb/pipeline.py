"""Embed Claude conversations, published artifacts, and Code sessions into MongoDB."""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from vectordb.blob_store import store as blob_store
from vectordb.classifier import classify_content
from vectordb.config import (
    COLLECTION_CODE_REPOS,
    COLLECTION_CODE_SESSIONS,
    COLLECTION_CONVERSATIONS,
    COLLECTION_MESSAGES,
    COLLECTION_PUBLISHED_ARTIFACTS,
)
from vectordb.db import ensure_forge_indexes, get_database
from vectordb.embeddings import embed_texts, get_voyage_client
from vectordb.events import emit_event

DATA_DIR = Path(__file__).parent.parent / "data"
CONVERSATIONS_DIR = DATA_DIR / "conversations"
PUBLISHED_DIR = DATA_DIR / "published_artifacts"
SESSIONS_DIR = DATA_DIR / "code_sessions"
REPOS_FILE = DATA_DIR / "code_repos.json"


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


def _embed_published_artifacts(db, voyage, force=False):
    """Embed published artifacts into the published_artifacts collection."""
    if not PUBLISHED_DIR.exists():
        return 0

    artifact_files = sorted(PUBLISHED_DIR.glob("*.json"))
    if not artifact_files:
        return 0

    col = db[COLLECTION_PUBLISHED_ARTIFACTS]
    embedded = 0

    for filepath in artifact_files:
        try:
            artifact = json.loads(filepath.read_text())
        except (json.JSONDecodeError, OSError):
            continue

        artifact_uuid = artifact.get("published_artifact_uuid", "")
        if not artifact_uuid:
            continue

        # Skip if already embedded
        if not force:
            existing = col.find_one(
                {"artifact_uuid": artifact_uuid},
                {"updated_at": 1},
            )
            if existing and existing.get("updated_at") == artifact.get("updated_at", ""):
                continue

        # Build text for embedding from artifact content
        content = artifact.get("artifact_content", "")
        title = artifact.get("title", artifact.get("name", ""))
        embed_text = f"{title}\n\n{content}"[:8000] if content else title[:4000]
        if len(embed_text.strip()) < 5:
            continue

        content_type = classify_content(embed_text)
        embeddings = embed_texts([embed_text], client=voyage)

        # Extract conversation/project context from the artifact
        conversation_uuid = artifact.get("conversation_uuid", "")
        project_name = artifact.get("project_name", "")

        content_blob_ref = blob_store(content) if content else None

        update_doc = {
            "artifact_uuid": artifact_uuid,
            "title": title,
            "content": content[:4000],
            "embedding": embeddings[0],
            "content_type": content_type,
            "conversation_id": conversation_uuid,
            "project_name": project_name,
            "artifact_type": artifact.get("type", ""),
            "language": artifact.get("language", ""),
            "created_at": artifact.get("created_at", ""),
            "updated_at": artifact.get("updated_at", ""),
            "metadata": {
                k: v for k, v in artifact.items()
                if k not in (
                    "published_artifact_uuid", "artifact_content",
                    "title", "name", "type", "language",
                    "created_at", "updated_at", "conversation_uuid",
                    "project_name",
                )
            },
        }
        if content_blob_ref:
            update_doc["content_blob_ref"] = content_blob_ref

        col.update_one(
            {"artifact_uuid": artifact_uuid},
            {"$set": update_doc},
            upsert=True,
        )
        embedded += 1

    return embedded


def _embed_code_sessions(db, voyage, force=False):
    """Embed Claude Code sessions into the code_sessions collection."""
    if not SESSIONS_DIR.exists():
        return 0

    session_files = sorted(SESSIONS_DIR.glob("*.json"))
    if not session_files:
        return 0

    col = db[COLLECTION_CODE_SESSIONS]
    embedded = 0

    for filepath in session_files:
        try:
            session = json.loads(filepath.read_text())
        except (json.JSONDecodeError, OSError):
            continue

        session_id = session.get("id") or session.get("uuid", "")
        if not session_id:
            continue

        # Skip if already embedded and unchanged
        if not force:
            existing = col.find_one(
                {"session_id": session_id},
                {"updated_at": 1},
            )
            if existing and existing.get("updated_at") == session.get("updated_at", ""):
                continue

        # Build text from session context for embedding
        title = session.get("title", session.get("name", ""))
        context = session.get("session_context", {})
        model = context.get("model", session.get("model", ""))

        # Collect text from sources and outcomes if available
        text_parts = [title] if title else []
        for source in context.get("sources", []):
            if isinstance(source, dict) and source.get("content"):
                text_parts.append(str(source["content"])[:1000])
            elif isinstance(source, str):
                text_parts.append(source[:1000])
        for outcome in context.get("outcomes", []):
            if isinstance(outcome, dict) and outcome.get("content"):
                text_parts.append(str(outcome["content"])[:1000])
            elif isinstance(outcome, str):
                text_parts.append(outcome[:1000])

        # Also check for a summary or description
        if session.get("summary"):
            text_parts.append(session["summary"])

        embed_text = "\n".join(text_parts)[:8000]
        if len(embed_text.strip()) < 5:
            continue

        content_type = classify_content(embed_text)
        embeddings = embed_texts([embed_text], client=voyage)

        # Extract project context
        project_name = session.get("project_name", "")
        env_id = session.get("environment_id", "")

        summary_blob_ref = blob_store(embed_text)

        update_doc = {
            "session_id": session_id,
            "title": title,
            "summary": embed_text[:2000],
            "embedding": embeddings[0],
            "content_type": content_type,
            "model": model,
            "status": session.get("status", ""),
            "project_name": project_name,
            "environment_id": env_id,
            "created_at": session.get("created_at", ""),
            "updated_at": session.get("updated_at", ""),
            "metadata": {
                "source_count": len(context.get("sources", [])),
                "outcome_count": len(context.get("outcomes", [])),
            },
        }
        if summary_blob_ref:
            update_doc["summary_blob_ref"] = summary_blob_ref

        col.update_one(
            {"session_id": session_id},
            {"$set": update_doc},
            upsert=True,
        )
        embedded += 1

    return embedded


def _ingest_code_repos(db):
    """Ingest code repo metadata (no embedding — metadata only)."""
    if not REPOS_FILE.exists():
        return 0

    try:
        repos = json.loads(REPOS_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return 0

    if not isinstance(repos, list):
        return 0

    col = db[COLLECTION_CODE_REPOS]
    ingested = 0

    for entry in repos:
        # Handle nested {repo: {...}, status: ...} format from Claude API
        repo = entry.get("repo", entry) if isinstance(entry, dict) else entry
        if not isinstance(repo, dict):
            continue

        owner = repo.get("owner", {})
        owner_login = owner.get("login", "") if isinstance(owner, dict) else ""
        name = repo.get("name", "")
        if not name:
            continue

        # Use owner/name as unique identifier (no UUID in this API)
        full_name = f"{owner_login}/{name}" if owner_login else name

        col.update_one(
            {"full_name": full_name},
            {
                "$set": {
                    "full_name": full_name,
                    "name": name,
                    "owner": owner_login,
                    "owner_type": owner.get("type", "") if isinstance(owner, dict) else "",
                    "default_branch": repo.get("default_branch", "main"),
                    "visibility": repo.get("visibility", ""),
                    "archived": repo.get("archived", False),
                    "status": entry.get("status"),
                    "synced_at": datetime.now(timezone.utc).isoformat(),
                }
            },
            upsert=True,
        )
        ingested += 1

    return ingested


def run_pipeline(force=False):
    """Main embedding pipeline: reads conversations, embeds, stores in MongoDB.

    Args:
        force: If True, re-embed all conversations regardless of updated_at.
    """
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

    stats = {
        "conversations_embedded": 0,
        "messages_embedded": 0,
        "skipped": 0,
        "published_artifacts": 0,
        "code_sessions": 0,
        "code_repos": 0,
    }

    for i, filepath in enumerate(conversation_files):
        conv = _load_conversation(filepath)
        if conv is None:
            continue

        conv_id = conv.get("uuid", "")
        conv_name = conv.get("name") or "(Untitled)"
        updated_at = conv.get("updated_at", "")
        progress = f"[{i + 1}/{len(conversation_files)}]"

        # Skip if already embedded with same updated_at
        if not force:
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

    # Embed published artifacts, code sessions, and ingest code repos
    print("\nProcessing published artifacts...")
    stats["published_artifacts"] = _embed_published_artifacts(db, voyage, force=force)

    print("Processing Claude Code sessions...")
    stats["code_sessions"] = _embed_code_sessions(db, voyage, force=force)

    print("Ingesting code repos...")
    stats["code_repos"] = _ingest_code_repos(db)

    emit_event(
        "memory.pipeline.completed",
        {
            "conversations_embedded": stats["conversations_embedded"],
            "messages_embedded": stats["messages_embedded"],
            "skipped": stats["skipped"],
            "published_artifacts": stats["published_artifacts"],
            "code_sessions": stats["code_sessions"],
            "code_repos": stats["code_repos"],
        },
        db=db,
    )

    print(f"\nPipeline complete!")
    print(f"  Conversations embedded: {stats['conversations_embedded']}")
    print(f"  Messages embedded:      {stats['messages_embedded']}")
    print(f"  Skipped (unchanged):    {stats['skipped']}")
    print(f"  Published artifacts:    {stats['published_artifacts']}")
    print(f"  Code sessions:          {stats['code_sessions']}")
    print(f"  Code repos:             {stats['code_repos']}")


if __name__ == "__main__":
    run_pipeline(force="--force" in sys.argv)
