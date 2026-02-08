import os
from pathlib import Path

# Load .env file from project root if present
_env_path = Path(__file__).parent.parent / ".env"
if _env_path.exists():
    for line in _env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())

MONGODB_URI = os.environ.get(
    "MONGODB_URI", "mongodb://localhost:27017/?directConnection=true"
)
DATABASE_NAME = "claude_search"

VOYAGE_API_KEY = os.environ.get("VOYAGE_API_KEY", "")
VOYAGE_MODEL = "voyage-3"
EMBEDDING_DIMENSIONS = 1024
VOYAGE_BATCH_SIZE = 128

COLLECTION_MESSAGES = "message_embeddings"
COLLECTION_CONVERSATIONS = "conversation_embeddings"
COLLECTION_DOCUMENTS = "document_embeddings"

# Forge OS Layer 1: MEMORY collections
COLLECTION_PATTERNS = "patterns"
COLLECTION_SCRATCHPAD = "scratchpad"
COLLECTION_ARCHIVE = "archive"
COLLECTION_EVENTS = "memory_events"

# Forge OS Layer 0: extended data collections
COLLECTION_PUBLISHED_ARTIFACTS = "published_artifacts"
COLLECTION_CODE_SESSIONS = "code_sessions"
COLLECTION_CODE_REPOS = "code_repos"

VECTOR_INDEX_NAME = "vector_index"

# Content type classification constants
CONTENT_TYPE_CONVERSATION = "conversation"
CONTENT_TYPE_CODE_PATTERN = "code_pattern"
CONTENT_TYPE_ERROR_RECOVERY = "error_recovery"
CONTENT_TYPE_DECISION = "decision"
CONTENT_TYPE_SOLUTION = "solution"
CONTENT_TYPE_OPTIMIZATION = "optimization"
CONTENT_TYPE_ROUTING = "routing"

CONTENT_TYPES = (
    CONTENT_TYPE_CONVERSATION,
    CONTENT_TYPE_CODE_PATTERN,
    CONTENT_TYPE_ERROR_RECOVERY,
    CONTENT_TYPE_DECISION,
    CONTENT_TYPE_SOLUTION,
    CONTENT_TYPE_OPTIMIZATION,
    CONTENT_TYPE_ROUTING,
)

# Pattern store configuration
PATTERN_TYPES = ("routing", "execution", "error_recovery", "optimization")
PATTERN_MERGE_THRESHOLD = 0.9
PATTERN_CONFIDENCE_SIMILARITY_WEIGHT = 0.6
PATTERN_CONFIDENCE_SCORE_WEIGHT = 0.4
PATTERN_DEFAULT_LIMIT = 5

# Scratchpad TTL (seconds) — default 1 hour
SCRATCHPAD_DEFAULT_TTL = 3600

# Archive retention policies (days)
RETENTION_DAYS_30 = 30
RETENTION_DAYS_90 = 90
RETENTION_DAYS_365 = 365
RETENTION_PERMANENT = "permanent"

# Events TTL — 90 days in seconds
EVENTS_TTL_SECONDS = 90 * 24 * 60 * 60
