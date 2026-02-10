from pymongo import MongoClient
from pymongo.errors import OperationFailure

from vectordb.config import (
    COLLECTION_ARCHIVE,
    COLLECTION_CODE_REPOS,
    COLLECTION_CODE_SESSIONS,
    COLLECTION_CONVERSATIONS,
    COLLECTION_COMPRESSION_REGISTRY,
    COLLECTION_CONVERSATION_REGISTRY,
    COLLECTION_DECISION_REGISTRY,
    COLLECTION_DOCUMENTS,
    COLLECTION_ENTANGLEMENT_SCANS,
    COLLECTION_EVENTS,
    COLLECTION_EXPEDITION_FLAGS,
    COLLECTION_LINEAGE_EDGES,
    COLLECTION_MESSAGES,
    COLLECTION_PATTERNS,
    COLLECTION_PRIMING_REGISTRY,
    COLLECTION_PUBLISHED_ARTIFACTS,
    COLLECTION_SCRATCHPAD,
    COLLECTION_THREAD_REGISTRY,
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

    # --- Thread registry collection ---
    thread_registry = db[COLLECTION_THREAD_REGISTRY]
    thread_registry.create_index("uuid", unique=True)
    thread_registry.create_index([("project", 1), ("status", 1)])
    thread_registry.create_index([("status", 1), ("updated_at", 1)])
    _create_filtered_vector_index(
        thread_registry,
        VECTOR_INDEX_NAME,
        filter_fields=["project", "status"],
    )

    # --- Decision registry collection ---
    decision_registry = db[COLLECTION_DECISION_REGISTRY]
    decision_registry.create_index("uuid", unique=True)
    decision_registry.create_index([("project", 1), ("status", 1)])
    decision_registry.create_index("text_hash")
    decision_registry.create_index([("status", 1), ("last_validated", 1)])
    _create_filtered_vector_index(
        decision_registry,
        VECTOR_INDEX_NAME,
        filter_fields=["project", "status"],
    )

    # --- Conversation registry collection ---
    conversation_registry = db[COLLECTION_CONVERSATION_REGISTRY]
    conversation_registry.create_index("uuid", unique=True)
    conversation_registry.create_index("source_id", unique=True)
    conversation_registry.create_index("project_name")
    conversation_registry.create_index("project_uuid")
    conversation_registry.create_index("created_at_ms")

    # --- Lineage edges collection ---
    lineage_edges = db[COLLECTION_LINEAGE_EDGES]
    lineage_edges.create_index("edge_uuid", unique=True)
    lineage_edges.create_index("source_conversation")
    lineage_edges.create_index("target_conversation")
    lineage_edges.create_index("compression_tag")
    lineage_edges.create_index("source_project")
    lineage_edges.create_index("target_project")

    # --- Compression registry collection ---
    compression_registry = db[COLLECTION_COMPRESSION_REGISTRY]
    compression_registry.create_index("compression_tag", unique=True)
    compression_registry.create_index("project")
    compression_registry.create_index("source_conversation")
    compression_registry.create_index("created_at")

    # --- Priming registry collection ---
    priming_registry = db[COLLECTION_PRIMING_REGISTRY]
    priming_registry.create_index("uuid", unique=True)
    priming_registry.create_index([("project", 1), ("status", 1)])
    priming_registry.create_index("territory_name")
    priming_registry.create_index("content_hash")
    _create_filtered_vector_index(
        priming_registry,
        VECTOR_INDEX_NAME,
        filter_fields=["project", "status"],
    )

    # --- Expedition flags collection ---
    expedition_flags = db[COLLECTION_EXPEDITION_FLAGS]
    expedition_flags.create_index("uuid", unique=True)
    expedition_flags.create_index([("project", 1), ("status", 1)])
    expedition_flags.create_index([("project", 1), ("category", 1)])
    expedition_flags.create_index("conversation_id")

    # --- Entanglement scans collection ---
    entanglement_scans = db[COLLECTION_ENTANGLEMENT_SCANS]
    entanglement_scans.create_index("scan_id", unique=True)
    entanglement_scans.create_index("scanned_at")
    entanglement_scans.create_index("project")

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
        "conversation_registry": conversation_registry,
        "thread_registry": thread_registry,
        "decision_registry": decision_registry,
        "lineage_edges": lineage_edges,
        "compression_registry": compression_registry,
        "priming_registry": priming_registry,
        "expedition_flags": expedition_flags,
        "entanglement_scans": entanglement_scans,
    }


def is_mongodb_available():
    """Check if MongoDB is running and reachable."""
    try:
        client = get_client()
        client.admin.command("ping")
        return True
    except Exception:
        return False
