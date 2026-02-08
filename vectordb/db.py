from pymongo import MongoClient
from pymongo.errors import OperationFailure

from vectordb.config import (
    COLLECTION_ARCHIVE,
    COLLECTION_CODE_REPOS,
    COLLECTION_CODE_SESSIONS,
    COLLECTION_CONVERSATIONS,
    COLLECTION_DOCUMENTS,
    COLLECTION_EVENTS,
    COLLECTION_MESSAGES,
    COLLECTION_PATTERNS,
    COLLECTION_PUBLISHED_ARTIFACTS,
    COLLECTION_SCRATCHPAD,
    DATABASE_NAME,
    EMBEDDING_DIMENSIONS,
    EVENTS_TTL_SECONDS,
    MONGODB_URI,
    VECTOR_INDEX_NAME,
)


def get_client():
    return MongoClient(MONGODB_URI)


def get_database(client=None):
    if client is None:
        client = get_client()
    return client[DATABASE_NAME]


def _create_vector_index(collection, index_name, path="embedding"):
    """Create an Atlas vector search index if it doesn't already exist."""
    existing = list(collection.list_search_indexes())
    for idx in existing:
        if idx.get("name") == index_name:
            return

    index_definition = {
        "definition": {
            "fields": [
                {
                    "path": path,
                    "numDimensions": EMBEDDING_DIMENSIONS,
                    "similarity": "cosine",
                    "type": "vector",
                }
            ]
        },
        "name": index_name,
        "type": "vectorSearch",
    }

    try:
        collection.create_search_index(index_definition)
    except OperationFailure as err:
        if "already exists" not in str(err):
            raise


def ensure_indexes(db=None):
    """Create all vector search indexes and standard indexes."""
    if db is None:
        db = get_database()

    messages = db[COLLECTION_MESSAGES]
    conversations = db[COLLECTION_CONVERSATIONS]
    documents = db[COLLECTION_DOCUMENTS]

    # Standard indexes for filtering
    messages.create_index("conversation_id")
    messages.create_index("project_name")
    conversations.create_index("conversation_id", unique=True)
    conversations.create_index("project_name")
    documents.create_index("source")

    # Vector search indexes
    _create_vector_index(messages, VECTOR_INDEX_NAME)
    _create_vector_index(conversations, VECTOR_INDEX_NAME)
    _create_vector_index(documents, VECTOR_INDEX_NAME)

    return {
        "messages": messages,
        "conversations": conversations,
        "documents": documents,
    }


def _create_filtered_vector_index(collection, index_name, filter_fields, path="embedding"):
    """Create a vector search index with filter fields.

    Drops and recreates if filter fields have changed.
    """
    existing = list(collection.list_search_indexes())
    for idx in existing:
        if idx.get("name") == index_name:
            # Check if filter fields match — if so, skip
            existing_fields = idx.get("latestDefinition", {}).get("fields", [])
            existing_filter_paths = sorted(
                f.get("path", "") for f in existing_fields if f.get("type") == "filter"
            )
            requested_filter_paths = sorted(filter_fields)
            if existing_filter_paths == requested_filter_paths:
                return
            # Filter fields changed — drop and recreate
            try:
                collection.drop_search_index(index_name)
            except OperationFailure:
                pass
            break

    fields = [
        {
            "path": path,
            "numDimensions": EMBEDDING_DIMENSIONS,
            "similarity": "cosine",
            "type": "vector",
        }
    ]
    for filter_path in filter_fields:
        fields.append({"type": "filter", "path": filter_path})

    index_definition = {
        "definition": {"fields": fields},
        "name": index_name,
        "type": "vectorSearch",
    }

    try:
        collection.create_search_index(index_definition)
    except OperationFailure as err:
        if "already exists" not in str(err):
            raise


def ensure_forge_indexes(db=None):
    """Create all Forge OS Layer 1: MEMORY indexes.

    This includes filtered vector search indexes on existing collections
    and setup for the 4 new collections (patterns, scratchpad, archive, events).
    """
    if db is None:
        db = get_database()

    messages = db[COLLECTION_MESSAGES]
    conversations = db[COLLECTION_CONVERSATIONS]
    documents = db[COLLECTION_DOCUMENTS]
    patterns = db[COLLECTION_PATTERNS]
    scratchpad = db[COLLECTION_SCRATCHPAD]
    archive = db[COLLECTION_ARCHIVE]
    events = db[COLLECTION_EVENTS]

    # --- Existing collections: standard indexes ---
    messages.create_index("conversation_id")
    messages.create_index("project_name")
    messages.create_index("content_type")
    messages.create_index("sender")
    conversations.create_index("conversation_id", unique=True)
    conversations.create_index("project_name")
    conversations.create_index("content_type")
    documents.create_index("source_id")
    documents.create_index("project_uuid")
    documents.create_index("source_type")

    # --- Existing collections: filtered vector search indexes ---
    _create_filtered_vector_index(
        messages,
        VECTOR_INDEX_NAME,
        filter_fields=["content_type", "sender", "project_name", "metadata.is_starred"],
    )
    _create_filtered_vector_index(
        conversations,
        VECTOR_INDEX_NAME,
        filter_fields=["content_type", "project_name", "is_starred", "platform"],
    )
    _create_filtered_vector_index(
        documents,
        VECTOR_INDEX_NAME,
        filter_fields=["content_type", "source_type", "project_uuid", "project_name"],
    )

    # --- Patterns collection ---
    patterns.create_index("pattern_id", unique=True)
    patterns.create_index("pattern_type")
    patterns.create_index("tags")
    _create_filtered_vector_index(
        patterns,
        VECTOR_INDEX_NAME,
        filter_fields=["pattern_type"],
    )

    # --- Scratchpad collection ---
    scratchpad.create_index(
        [("context_id", 1), ("key", 1)],
        unique=True,
    )
    scratchpad.create_index("expires_at", expireAfterSeconds=0)

    # --- Archive collection ---
    archive.create_index("archive_id", unique=True)
    archive.create_index("source_collection")
    archive.create_index("source_id")
    archive.create_index("retention_policy")
    archive.create_index("expires_at", expireAfterSeconds=0)

    # --- Memory events collection ---
    events.create_index("event_type")
    events.create_index("timestamp")
    events.create_index("expires_at", expireAfterSeconds=0)

    # --- Published artifacts collection ---
    published_artifacts = db[COLLECTION_PUBLISHED_ARTIFACTS]
    published_artifacts.create_index("artifact_uuid", unique=True)
    published_artifacts.create_index("conversation_id")
    published_artifacts.create_index("project_name")
    published_artifacts.create_index("content_type")
    _create_filtered_vector_index(
        published_artifacts,
        VECTOR_INDEX_NAME,
        filter_fields=["content_type", "project_name"],
    )

    # --- Code sessions collection ---
    code_sessions = db[COLLECTION_CODE_SESSIONS]
    code_sessions.create_index("session_id", unique=True)
    code_sessions.create_index("project_name")
    code_sessions.create_index("status")
    code_sessions.create_index("content_type")
    _create_filtered_vector_index(
        code_sessions,
        VECTOR_INDEX_NAME,
        filter_fields=["content_type", "project_name", "status"],
    )

    # --- Code repos collection (no vector index — metadata only) ---
    code_repos = db[COLLECTION_CODE_REPOS]
    code_repos.create_index("full_name", unique=True)
    code_repos.create_index("owner")

    return {
        "messages": messages,
        "conversations": conversations,
        "documents": documents,
        "patterns": patterns,
        "scratchpad": scratchpad,
        "archive": archive,
        "events": events,
        "published_artifacts": published_artifacts,
        "code_sessions": code_sessions,
        "code_repos": code_repos,
    }


def is_mongodb_available():
    """Check if MongoDB is running and reachable."""
    try:
        client = get_client()
        client.admin.command("ping")
        return True
    except Exception:
        return False
