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

# Forge OS Layer 2: GRAPH collections
COLLECTION_THREAD_REGISTRY = "thread_registry"
COLLECTION_DECISION_REGISTRY = "decision_registry"
COLLECTION_LINEAGE_EDGES = "lineage_edges"
COLLECTION_COMPRESSION_REGISTRY = "compression_registry"

# Forge OS Layer 2: GRAPH — identity registry
COLLECTION_CONVERSATION_REGISTRY = "conversation_registry"

# Forge OS Layer 2: GRAPH — global display IDs
COLLECTION_DISPLAY_ID_COUNTERS = "display_id_counters"
COLLECTION_DISPLAY_ID_INDEX = "display_id_index"

# Forge OS Layer 2.5: EXPEDITION collections
COLLECTION_PRIMING_REGISTRY = "priming_registry"
COLLECTION_EXPEDITION_FLAGS = "expedition_flags"

# Priming block similarity threshold for territory matching
PRIMING_TERRITORY_MATCH_THRESHOLD = 0.7

# Conflict detection thresholds
DECISION_CONFLICT_SIMILARITY_THRESHOLD = 0.85
STALE_MAX_HOPS = 3
STALE_MAX_DAYS = 30

# Entanglement discovery thresholds
ENTANGLEMENT_STRONG_THRESHOLD = 0.65
ENTANGLEMENT_WEAK_THRESHOLD = 0.50
COLLECTION_ENTANGLEMENT_SCANS = "entanglement_scans"

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

# Attention engine configuration
ATTENTION_WEIGHTS = {
    "similarity": 0.45,
    "epistemic_tier": 0.20,
    "freshness": 0.15,
    "conflict_salience": 0.10,
    "category_boost": 0.10,
}

CATEGORY_BOOSTS = {
    "decision": 1.0,
    "thread": 0.8,
    "priming": 0.6,
    "pattern": 0.4,
    "conversation": 0.2,
    "message": 0.0,
}

ATTENTION_DEFAULT_BUDGET = 4000
ATTENTION_FRESHNESS_HALF_LIFE = 30  # days
ATTENTION_MIN_SCORE = 0.1

# Gravity assist configuration (Layer 3.5)
COLLECTION_PROJECT_ROLES = "project_roles"
COLLECTION_LENS_CONFIGURATIONS = "lens_configurations"

GRAVITY_DEFAULT_BUDGET = 6000
GRAVITY_CONVERGENCE_BOOST = 1.3
GRAVITY_CONVERGENCE_THRESHOLD = 0.70
GRAVITY_DIVERGENCE_TIER_DELTA = 0.25
GRAVITY_MAX_LENSES = 6
GRAVITY_BASELINE_COHERENCE = 0.5

# Blob store configuration (content-addressed storage)
BLOB_STORE_BACKEND = os.environ.get("BLOB_STORE_BACKEND", "local")
BLOB_STORE_LOCAL_PATH = str(Path(__file__).parent.parent / "data" / "blobs")
BLOB_STORE_GCS_BUCKET = os.environ.get("BLOB_STORE_GCS_BUCKET", "")
BLOB_STORE_ENABLED = os.environ.get("BLOB_STORE_ENABLED", "true").lower() == "true"
