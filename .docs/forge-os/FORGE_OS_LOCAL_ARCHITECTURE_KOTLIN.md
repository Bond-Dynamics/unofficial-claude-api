# Forge OS: Local Architecture (Kotlin Edition)

## Mac Studio Deployment — Breaking the Sandbox

---

## The Problem

**Claude Projects are sandboxed:**
- Project A cannot see Project B
- No programmatic orchestration
- Manual copy-paste to transfer context
- The Nexus works but requires human shuttle
- Can't route to external models

**The Solution:** Move orchestration LOCAL. Claude becomes one model among many, accessed via API. All projects become a unified knowledge base.

---

## Technology Stack

### Core Runtime

| Component | Technology | Rationale |
|-----------|------------|-----------|
| **Language** | Kotlin 2.0+ | Type safety, coroutines, JVM ecosystem |
| **HTTP Framework** | Ktor | Native Kotlin, lightweight, coroutine-first |
| **Async** | Kotlinx.coroutines | Structured concurrency, cancellation |
| **Serialization** | Kotlinx.serialization | Native Kotlin, compile-time safe |
| **DI** | Koin | Lightweight, Kotlin DSL |
| **Build** | Gradle (Kotlin DSL) | Standard, powerful |

### Data Layer

| Component | Technology | Use Case |
|-----------|------------|----------|
| **Relational DB** | PostgreSQL 16+ | Relational data, cost tracking, routing logs, model registry |
| **Relational Search** | pgvector extension | Secondary vector search (structured knowledge embeddings) |
| **Document DB** | MongoDB 7+ | Conversations, archives, thread/decision registries, lineage graph |
| **Vector Search** | Atlas Vector Search + VoyageAI | Primary semantic search, conflict detection, context assembly |
| **Cache/Queue** | Redis 7+ | Sessions, rate limiting, task queues |
| **File Storage** | Local filesystem | Raw documents (git-versioned) |
| **SQL Client** | Exposed (JetBrains) | Type-safe SQL DSL for PostgreSQL |
| **MongoDB Client** | KMongo / Official Kotlin Driver | Type-safe MongoDB operations |

### Why This Stack?

**Dual Database — Each Does What It's Best At:**

**PostgreSQL for Relational/Structured Data:**
- Model registry, routing logs, cost tracking, personas — naturally relational
- Strong ACID guarantees for financial data and audit trails
- pgvector available as secondary vector index for structured knowledge embeddings
- Mature, battle-tested, excellent tooling

**MongoDB for Documents, Graphs, and Vector Search:**
- Conversations, archives, knowledge chunks — naturally document-shaped
- Thread registry, decision registry, lineage edges — schema-flexible, evolving rapidly
- Atlas Vector Search with VoyageAI embeddings — the same stack proven in the Python stepping stone
- No impedance mismatch: documents go in as documents, not squeezed into relational tables
- Direct migration path from the stepping stone codebase (same MongoDB collections, same VoyageAI embeddings)

**Redis for Ephemeral/Real-time:**
- Sub-millisecond caching
- Session state (conversation context)
- Rate limiting per model
- Task queue (Lettuce client)
- Pub/sub for real-time updates

**Why Not Just PostgreSQL?** The stepping stone codebase already has MongoDB with Atlas Vector Search + VoyageAI working. Thread registries, decision registries, lineage edges, and conversation archives are document-shaped and evolve rapidly — MongoDB handles this naturally. PostgreSQL handles the relational data (models, routing, costs) where schema stability and joins matter. Using both avoids forcing document workloads into relational tables and preserves continuity with the stepping stone.

### Model Integration

| Model Source | Client | Use Case |
|--------------|--------|----------|
| Claude | anthropic-sdk-kotlin (or HTTP) | Reasoning, coding, writing |
| Gemini | google-cloud-vertexai | Long context, multimodal |
| Local LLMs | Ollama HTTP API | Privacy, offline, free |
| Embeddings | VoyageAI API (primary), Ollama (fallback) | Vector generation for Atlas Vector Search |

### Interface Layer

| Interface | Technology | Use Case |
|-----------|------------|----------|
| CLI | Clikt | Power users, scripting |
| Web UI | Ktor + HTMX or Kotlin/JS | Visual chat |
| API | Ktor + OpenAPI | Automation, integrations |
| Desktop | Compose Multiplatform | Native macOS app (future) |

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                              MAC STUDIO                                         │
│                                                                                 │
│  ┌───────────────────────────────────────────────────────────────────────────┐  │
│  │                           FORGE OS CORE (Kotlin/JVM)                      │  │
│  │                                                                           │  │
│  │   ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐       │  │
│  │   │ KERNEL  │  │ ARBITER │  │EVALUATOR│  │ MISSION │  │GUARDIAN │       │  │
│  │   │execute()│  │ route() │  │evaluate()│ │CONTROL  │  │validate()│      │  │
│  │   │schedule │  │failover()│ │  gate() │  │  plan() │  │ audit() │       │  │
│  │   └────┬────┘  └────┬────┘  └────┬────┘  └────┬────┘  └────┬────┘       │  │
│  │        └────────────┴───────────┴────────────┴────────────┘             │  │
│  │                                    │                                     │  │
│  │                           ┌────────┴────────┐                           │  │
│  │                           │  ORCHESTRATOR   │                           │  │
│  │                           │    (Ktor)       │                           │  │
│  │                           └────────┬────────┘                           │  │
│  └───────────────────────────────────┼───────────────────────────────────────┘  │
│                                      │                                          │
│  ┌───────────────────────────────────┴───────────────────────────────────────┐  │
│  │                           DATA LAYER                                      │  │
│  │                                                                           │  │
│  │  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐       │  │
│  │  │   PostgreSQL     │  │     MongoDB      │  │      Redis       │       │  │
│  │  │  ┌────────────┐  │  │  ┌────────────┐  │  │  ┌────────────┐  │       │  │
│  │  │  │ models     │  │  │  │ messages   │  │  │  │ session    │  │       │  │
│  │  │  │ routing    │  │  │  │ archives   │  │  │  │ cache      │  │       │  │
│  │  │  │ cost_daily │  │  │  │ threads    │  │  │  │ rate limit │  │       │  │
│  │  │  │ personas   │  │  │  │ decisions  │  │  │  │ task queue │  │       │  │
│  │  │  │ pgvector   │  │  │  │ lineage    │  │  │  │ pub/sub    │  │       │  │
│  │  │  └────────────┘  │  │  │ embeddings │  │  │  └────────────┘  │       │  │
│  │  │                  │  │  │ (Atlas+    │  │  │                  │       │  │
│  │  │                  │  │  │  VoyageAI) │  │  │                  │       │  │
│  │  │                  │  │  └────────────┘  │  │                  │       │  │
│  │  └──────────────────┘  └──────────────────┘  └──────────────────┘       │  │
│  │                                                                           │  │
│  │  ┌─────────────────────────────────────────────────────────────────┐    │  │
│  │  │                    File System (Git-versioned)                   │    │  │
│  │  │  ~/forge-os/knowledge/projects/*, prompts/*, configs/*          │    │  │
│  │  └─────────────────────────────────────────────────────────────────┘    │  │
│  └───────────────────────────────────────────────────────────────────────────┘  │
│                                      │                                          │
│  ┌───────────────────────────────────┴───────────────────────────────────────┐  │
│  │                         MODEL INTERFACE LAYER                             │  │
│  │                                                                           │  │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐     │  │
│  │  │  Anthropic  │  │   Google    │  │   Ollama    │  │ Specialized │     │  │
│  │  │  (Claude)   │  │  (Gemini)   │  │   (Local)   │  │  (Whisper,  │     │  │
│  │  │   API       │  │    API      │  │   Models    │  │   SDXL...)  │     │  │
│  │  └─────────────┘  └─────────────┘  └─────────────┘  └─────────────┘     │  │
│  └───────────────────────────────────────────────────────────────────────────┘  │
│                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘
```

---

## Database Schema

### PostgreSQL Tables (Relational Data)

PostgreSQL handles structured, relational data where schema stability, joins, and ACID guarantees matter.

```sql
-- Enable pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- ════════════════════════════════════════════════════════════════
-- MODEL REGISTRY
-- ════════════════════════════════════════════════════════════════

CREATE TABLE models (
    id              VARCHAR(64) PRIMARY KEY,
    provider        VARCHAR(32) NOT NULL,  -- anthropic, google, ollama
    model_type      VARCHAR(16) NOT NULL,  -- cloud, local, specialized
    display_name    VARCHAR(128),
    
    -- Capabilities (0.0 - 1.0)
    cap_reasoning   DECIMAL(3,2),
    cap_coding      DECIMAL(3,2),
    cap_creative    DECIMAL(3,2),
    cap_analysis    DECIMAL(3,2),
    cap_vision      DECIMAL(3,2),
    cap_long_ctx    DECIMAL(3,2),
    
    -- Constraints
    max_context     INTEGER NOT NULL,
    max_output      INTEGER NOT NULL,
    rate_limit      INTEGER,  -- requests per minute
    
    -- Cost (per 1K tokens)
    cost_input      DECIMAL(10,6),
    cost_output     DECIMAL(10,6),
    
    -- Metadata
    config          JSONB DEFAULT '{}',
    is_active       BOOLEAN DEFAULT true,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_models_provider ON models(provider);
CREATE INDEX idx_models_active ON models(is_active) WHERE is_active = true;

-- ════════════════════════════════════════════════════════════════
-- ROUTING LOGS
-- ════════════════════════════════════════════════════════════════

CREATE TABLE routing_logs (
    id              BIGSERIAL PRIMARY KEY,
    
    -- Request
    task_type       VARCHAR(64),
    task_hash       VARCHAR(64),  -- For deduplication analysis
    input_tokens    INTEGER,
    
    -- Decision
    selected_model  VARCHAR(64) REFERENCES models(id),
    strategy        VARCHAR(32),
    score           DECIMAL(5,4),
    score_breakdown JSONB,
    alternatives    JSONB,  -- [{model, score}]
    
    -- Execution
    output_tokens   INTEGER,
    latency_ms      INTEGER,
    success         BOOLEAN,
    error_type      VARCHAR(64),
    
    -- Cost
    cost_usd        DECIMAL(10,6),
    
    -- Context
    persona         VARCHAR(64),
    session_id      UUID,
    
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_routing_logs_model ON routing_logs(selected_model);
CREATE INDEX idx_routing_logs_created ON routing_logs(created_at);
CREATE INDEX idx_routing_logs_session ON routing_logs(session_id);

-- Partitioning for scale (optional)
-- CREATE TABLE routing_logs_2024_01 PARTITION OF routing_logs
--     FOR VALUES FROM ('2024-01-01') TO ('2024-02-01');

-- ════════════════════════════════════════════════════════════════
-- KNOWLEDGE BASE
-- ════════════════════════════════════════════════════════════════

CREATE TABLE knowledge_documents (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    
    -- Identity
    project         VARCHAR(64) NOT NULL,  -- transmutation_forge, etc.
    filename        VARCHAR(256),
    doc_type        VARCHAR(32),  -- knowledge, archive, synthesis
    
    -- Content
    content         TEXT NOT NULL,
    content_hash    VARCHAR(64),  -- For change detection
    
    -- Metadata
    metadata        JSONB DEFAULT '{}',
    
    -- Timestamps
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_knowledge_project ON knowledge_documents(project);
CREATE INDEX idx_knowledge_type ON knowledge_documents(doc_type);
CREATE INDEX idx_knowledge_metadata ON knowledge_documents USING GIN(metadata);

-- Full-text search
CREATE INDEX idx_knowledge_fts ON knowledge_documents 
    USING GIN(to_tsvector('english', content));

-- ════════════════════════════════════════════════════════════════
-- VECTOR EMBEDDINGS (pgvector)
-- ════════════════════════════════════════════════════════════════

CREATE TABLE knowledge_embeddings (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id     UUID REFERENCES knowledge_documents(id) ON DELETE CASCADE,
    
    -- Chunk info (documents split into chunks for embedding)
    chunk_index     INTEGER NOT NULL,
    chunk_text      TEXT NOT NULL,
    
    -- Vector (1536 dimensions for OpenAI/Voyage, 768 for nomic)
    embedding       vector(1536),
    
    -- Metadata
    metadata        JSONB DEFAULT '{}',
    
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- HNSW index for fast similarity search
CREATE INDEX idx_embeddings_vector ON knowledge_embeddings 
    USING hnsw (embedding vector_cosine_ops);

CREATE INDEX idx_embeddings_document ON knowledge_embeddings(document_id);

-- ════════════════════════════════════════════════════════════════
-- CONVERSATION ARCHIVES
-- ════════════════════════════════════════════════════════════════

CREATE TABLE conversation_archives (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id      VARCHAR(128) UNIQUE NOT NULL,
    
    -- Content (JSONB for flexibility)
    continuation    JSONB NOT NULL,  -- Compressed state
    full_archive    JSONB,           -- Full transcript (optional)
    
    -- Metadata
    persona         VARCHAR(64),
    turns           INTEGER,
    decisions       INTEGER,
    artifacts       INTEGER,
    
    -- Tags for retrieval
    tags            TEXT[],
    
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_archives_session ON conversation_archives(session_id);
CREATE INDEX idx_archives_persona ON conversation_archives(persona);
CREATE INDEX idx_archives_tags ON conversation_archives USING GIN(tags);

-- ════════════════════════════════════════════════════════════════
-- COST TRACKING
-- ════════════════════════════════════════════════════════════════

CREATE TABLE cost_daily (
    date            DATE NOT NULL,
    model_id        VARCHAR(64) REFERENCES models(id),
    
    request_count   INTEGER DEFAULT 0,
    input_tokens    BIGINT DEFAULT 0,
    output_tokens   BIGINT DEFAULT 0,
    total_cost_usd  DECIMAL(10,4) DEFAULT 0,
    
    PRIMARY KEY (date, model_id)
);

-- Materialized view for quick reporting
CREATE MATERIALIZED VIEW cost_monthly AS
SELECT 
    DATE_TRUNC('month', date) AS month,
    model_id,
    SUM(request_count) AS requests,
    SUM(input_tokens) AS input_tokens,
    SUM(output_tokens) AS output_tokens,
    SUM(total_cost_usd) AS total_cost
FROM cost_daily
GROUP BY 1, 2;

-- ════════════════════════════════════════════════════════════════
-- PERSONAS
-- ════════════════════════════════════════════════════════════════

CREATE TABLE personas (
    id              VARCHAR(64) PRIMARY KEY,
    display_name    VARCHAR(128) NOT NULL,
    description     TEXT,
    
    -- Configuration
    system_prompt   TEXT NOT NULL,
    knowledge_scope TEXT[] NOT NULL,  -- Project folders to include
    default_model   VARCHAR(64) REFERENCES models(id),
    temperature     DECIMAL(3,2) DEFAULT 0.7,
    
    -- Metadata
    config          JSONB DEFAULT '{}',
    is_active       BOOLEAN DEFAULT true,
    
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);
```

### MongoDB Collections (Documents, Vectors, Graph)

MongoDB handles document-shaped data, vector search (via Atlas Vector Search + VoyageAI), and the conversation lineage graph. These collections mirror and extend what already exists in the stepping stone codebase.

```javascript
// ════════════════════════════════════════════════════════════════
// CONVERSATIONS & ARCHIVES
// ════════════════════════════════════════════════════════════════

// Raw conversation data (migrated from stepping stone)
db.messages.createIndex({ conversation_id: 1 })
db.messages.createIndex({ project: 1, created_at: -1 })

// Conversation archives (compressed state)
// Schema: { session_id, continuation (BSON), full_archive, persona,
//           turns, decisions, artifacts, tags[], compression_tag,
//           created_at, updated_at }
db.conversation_archives.createIndex({ session_id: 1 }, { unique: true })
db.conversation_archives.createIndex({ persona: 1 })
db.conversation_archives.createIndex({ tags: 1 })
db.conversation_archives.createIndex({ compression_tag: 1 })

// ════════════════════════════════════════════════════════════════
// KNOWLEDGE BASE + VECTOR SEARCH
// ════════════════════════════════════════════════════════════════

// Knowledge chunks with VoyageAI embeddings
// Schema: { uuid, project, filename, doc_type, chunk_index,
//           chunk_text, embedding (float[1024]), content_hash,
//           metadata, created_at }
db.knowledge_chunks.createIndex({ project: 1 })
db.knowledge_chunks.createIndex({ doc_type: 1 })
db.knowledge_chunks.createIndex({ content_hash: 1 })

// Atlas Vector Search index (defined via Atlas UI or API)
// {
//   "name": "knowledge_vector_index",
//   "type": "vectorSearch",
//   "definition": {
//     "fields": [{
//       "type": "vector",
//       "path": "embedding",
//       "numDimensions": 1024,
//       "similarity": "cosine"
//     }]
//   }
// }

// ════════════════════════════════════════════════════════════════
// THREAD REGISTRY
// ════════════════════════════════════════════════════════════════

// Schema: { uuid, title, status, project, first_seen_conversation,
//           last_updated_conversation, priority, blocked_by[],
//           resolution, epistemic_tier, created_at, updated_at }
db.thread_registry.createIndex({ uuid: 1 }, { unique: true })
db.thread_registry.createIndex({ project: 1, status: 1 })
db.thread_registry.createIndex({ status: 1, updated_at: -1 })

// ════════════════════════════════════════════════════════════════
// DECISION REGISTRY
// ════════════════════════════════════════════════════════════════

// Schema: { uuid, text, text_hash, project, epistemic_tier,
//           originated_conversation, last_validated,
//           conflicts_with[], dependents[], superseded_by,
//           status, embedding (float[1024]), created_at, updated_at }
db.decision_registry.createIndex({ uuid: 1 }, { unique: true })
db.decision_registry.createIndex({ project: 1, status: 1 })
db.decision_registry.createIndex({ text_hash: 1 })
db.decision_registry.createIndex({ status: 1, last_validated: 1 })

// Atlas Vector Search index for conflict detection
// {
//   "name": "decision_vector_index",
//   "type": "vectorSearch",
//   "definition": {
//     "fields": [{
//       "type": "vector",
//       "path": "embedding",
//       "numDimensions": 1024,
//       "similarity": "cosine"
//     }]
//   }
// }

// ════════════════════════════════════════════════════════════════
// LINEAGE GRAPH
// ════════════════════════════════════════════════════════════════

// Schema: { edge_uuid, source_conversation, target_conversation,
//           compression_tag, edge_type, created_at }
db.lineage_edges.createIndex({ edge_uuid: 1 }, { unique: true })
db.lineage_edges.createIndex({ source_conversation: 1 })
db.lineage_edges.createIndex({ target_conversation: 1 })
db.lineage_edges.createIndex({ compression_tag: 1 })

// ════════════════════════════════════════════════════════════════
// PATTERNS & EVENTS (migrated from stepping stone)
// ════════════════════════════════════════════════════════════════

db.patterns.createIndex({ pattern_type: 1, project: 1 })
db.events.createIndex({ event_type: 1, created_at: -1 })
db.scratchpad.createIndex({ key: 1 }, { unique: true })
db.scratchpad.createIndex({ expires_at: 1 }, { expireAfterSeconds: 0 })
```

### Redis Data Structures

```
# ════════════════════════════════════════════════════════════════
# SESSION CACHE
# ════════════════════════════════════════════════════════════════

# Current conversation context (expires after 1 hour of inactivity)
session:{session_id}:context     -> JSON string of conversation state
session:{session_id}:persona     -> Current persona ID
session:{session_id}:model       -> Current model override (if any)
TTL: 3600 seconds

# ════════════════════════════════════════════════════════════════
# RATE LIMITING
# ════════════════════════════════════════════════════════════════

# Sliding window rate limit per model
ratelimit:{model_id}:minute      -> ZSET of request timestamps
ratelimit:{model_id}:tokens      -> Current token count this minute

# ════════════════════════════════════════════════════════════════
# TASK QUEUE
# ════════════════════════════════════════════════════════════════

# Async task queue (for batch operations, background jobs)
queue:tasks                      -> LIST (LPUSH/BRPOP)
queue:results:{task_id}          -> JSON result (with TTL)

# ════════════════════════════════════════════════════════════════
# CACHING
# ════════════════════════════════════════════════════════════════

# Model health cache
cache:model:{model_id}:health    -> JSON {healthy, latency_ms, last_check}
TTL: 60 seconds

# Embedding cache (avoid re-embedding same text)
cache:embedding:{text_hash}      -> Binary vector data
TTL: 86400 seconds (24 hours)

# Knowledge retrieval cache
cache:retrieval:{query_hash}     -> JSON array of document IDs
TTL: 300 seconds (5 minutes)

# ════════════════════════════════════════════════════════════════
# PUB/SUB CHANNELS
# ════════════════════════════════════════════════════════════════

# Real-time streaming responses
channel:stream:{session_id}      -> Token-by-token output

# System events
channel:events                   -> {type, payload} for monitoring
```

---

## Directory Structure

```
~/forge-os/
│
├── build.gradle.kts                # Root build file
├── settings.gradle.kts
├── gradle.properties
│
├── forge-core/                     # Core library
│   ├── build.gradle.kts
│   └── src/main/kotlin/
│       └── dev/forge/
│           ├── ForgeOS.kt          # Main entry point
│           │
│           ├── kernel/             # Execution control
│           │   ├── Kernel.kt
│           │   ├── Scheduler.kt
│           │   └── TaskContext.kt
│           │
│           ├── arbiter/            # Routing
│           │   ├── Arbiter.kt
│           │   ├── TaskAnalyzer.kt
│           │   ├── ModelScorer.kt
│           │   ├── RoutingPolicy.kt
│           │   └── Failover.kt
│           │
│           ├── evaluator/          # Quality control
│           │   ├── Evaluator.kt
│           │   ├── Criteria.kt
│           │   └── Gate.kt
│           │
│           ├── orchestrator/       # Coordination
│           │   ├── Orchestrator.kt
│           │   ├── Planner.kt
│           │   └── Workflow.kt
│           │
│           ├── guardian/           # Safety
│           │   ├── Guardian.kt
│           │   ├── Validator.kt
│           │   └── AuditLog.kt
│           │
│           ├── memory/             # Knowledge
│           │   ├── KnowledgeStore.kt
│           │   ├── Retriever.kt
│           │   ├── Embedder.kt
│           │   └── Chunker.kt
│           │
│           ├── models/             # Model adapters
│           │   ├── ModelAdapter.kt      # Interface
│           │   ├── AnthropicAdapter.kt
│           │   ├── GoogleAdapter.kt
│           │   ├── OllamaAdapter.kt
│           │   └── ModelRegistry.kt
│           │
│           ├── personas/           # Persona system
│           │   ├── Persona.kt
│           │   ├── PersonaLoader.kt
│           │   └── ContextBuilder.kt
│           │
│           ├── db/                 # Database layer
│           │   ├── Database.kt          # PostgreSQL connection (Exposed)
│           │   ├── MongoDatabase.kt     # MongoDB connection (Kotlin Driver)
│           │   ├── tables/              # Exposed table definitions (PostgreSQL)
│           │   │   ├── Models.kt
│           │   │   ├── RoutingLogs.kt
│           │   │   ├── CostDaily.kt
│           │   │   ├── Personas.kt
│           │   │   └── ...
│           │   ├── collections/         # MongoDB collection definitions
│           │   │   ├── Messages.kt
│           │   │   ├── Archives.kt
│           │   │   ├── KnowledgeChunks.kt
│           │   │   ├── ThreadRegistry.kt
│           │   │   ├── DecisionRegistry.kt
│           │   │   ├── LineageEdges.kt
│           │   │   └── ...
│           │   └── repositories/
│           │       ├── ModelRepository.kt       # PostgreSQL
│           │       ├── RoutingRepository.kt     # PostgreSQL
│           │       ├── KnowledgeRepository.kt   # MongoDB + Atlas Vector Search
│           │       ├── ThreadRepository.kt      # MongoDB
│           │       ├── DecisionRepository.kt    # MongoDB
│           │       ├── LineageRepository.kt     # MongoDB
│           │       └── ...
│           │
│           ├── cache/              # Redis layer
│           │   ├── RedisClient.kt
│           │   ├── SessionCache.kt
│           │   ├── RateLimiter.kt
│           │   └── TaskQueue.kt
│           │
│           └── config/             # Configuration
│               ├── Config.kt
│               └── ConfigLoader.kt
│
├── forge-cli/                      # CLI application
│   ├── build.gradle.kts
│   └── src/main/kotlin/
│       └── dev/forge/cli/
│           ├── Main.kt
│           └── commands/
│               ├── ChatCommand.kt
│               ├── RouteCommand.kt
│               ├── KnowledgeCommand.kt
│               ├── ModelsCommand.kt
│               └── ConfigCommand.kt
│
├── forge-server/                   # HTTP API server
│   ├── build.gradle.kts
│   └── src/main/kotlin/
│       └── dev/forge/server/
│           ├── Application.kt
│           ├── routes/
│           │   ├── ChatRoutes.kt
│           │   ├── KnowledgeRoutes.kt
│           │   └── AdminRoutes.kt
│           └── plugins/
│               ├── Serialization.kt
│               ├── Security.kt
│               └── Monitoring.kt
│
├── forge-web/                      # Web UI (optional)
│   ├── build.gradle.kts
│   └── src/main/
│       ├── kotlin/                 # Ktor serving
│       └── resources/
│           ├── templates/          # HTML templates
│           └── static/             # CSS, JS
│
├── knowledge/                      # Knowledge base (git-versioned)
│   ├── projects/
│   │   ├── transmutation_forge/
│   │   ├── reality_compiler/
│   │   ├── cartographers_codex/
│   │   ├── applied_alchemy/
│   │   ├── cth_2026/
│   │   └── forge_os/
│   ├── archives/
│   └── synthesis/
│
├── prompts/                        # System prompts (git-versioned)
│   └── personas/
│       ├── cartographer.md
│       ├── transmuter.md
│       ├── architect.md
│       └── nexus.md
│
├── configs/                        # Configuration files
│   ├── application.yaml
│   ├── models.yaml
│   ├── routing.yaml
│   └── personas.yaml
│
├── scripts/                        # Utility scripts
│   ├── setup.sh
│   ├── migrate.sh
│   └── import-claude-projects.kt
│
├── docker/
│   ├── docker-compose.yaml         # PostgreSQL + MongoDB + Redis
│   └── Dockerfile
│
└── docs/
    ├── ARCHITECTURE.md
    └── API.md
```

---

## Core Kotlin Components

### Arbiter

```kotlin
// forge-core/src/main/kotlin/dev/forge/arbiter/Arbiter.kt

package dev.forge.arbiter

import dev.forge.models.ModelAdapter
import dev.forge.models.ModelRegistry
import kotlinx.coroutines.flow.Flow

class Arbiter(
    private val registry: ModelRegistry,
    private val analyzer: TaskAnalyzer,
    private val scorer: ModelScorer,
    private val rateLimiter: RateLimiter
) {
    suspend fun route(request: RoutingRequest): RoutingDecision {
        // 1. Analyze task
        val analysis = analyzer.analyze(request.task, request.context)
        
        // 2. Get viable candidates
        val candidates = registry.getActiveModels()
            .filter { it.meetsConstraints(request.constraints) }
            .filter { rateLimiter.canRequest(it.id) }
        
        if (candidates.isEmpty()) {
            throw NoViableModelException("No models satisfy constraints")
        }
        
        // 3. Score candidates
        val scored = candidates
            .map { model -> 
                ScoredModel(
                    model = model,
                    score = scorer.score(model, analysis, request.policy)
                )
            }
            .sortedByDescending { it.score }
        
        // 4. Apply preference if viable
        request.preferredModel?.let { preferred ->
            scored.find { it.model.id == preferred }?.let { match ->
                if (match.score >= PREFERENCE_THRESHOLD) {
                    return RoutingDecision(
                        model = match.model,
                        reason = "User preference (viable)",
                        alternatives = scored.take(3)
                    )
                }
            }
        }
        
        // 5. Select best
        val selected = scored.first()
        
        return RoutingDecision(
            model = selected.model,
            reason = buildReason(selected, analysis, request),
            alternatives = scored.take(3),
            estimatedCost = estimateCost(selected.model, analysis)
        )
    }
    
    suspend fun execute(
        request: RoutingRequest
    ): Flow<String> {
        val decision = route(request)
        val adapter = registry.getAdapter(decision.model.id)
        
        return adapter.complete(
            messages = request.messages,
            systemPrompt = request.systemPrompt,
            temperature = request.temperature
        )
    }
    
    companion object {
        private const val PREFERENCE_THRESHOLD = 0.7
    }
}

data class RoutingRequest(
    val task: String,
    val context: String? = null,
    val messages: List<Message> = emptyList(),
    val systemPrompt: String? = null,
    val temperature: Double = 0.7,
    val constraints: Constraints = Constraints(),
    val policy: RoutingPolicy = RoutingPolicy.BALANCED,
    val preferredModel: String? = null
)

data class Constraints(
    val maxCost: Double? = null,
    val maxLatencyMs: Int? = null,
    val requireLocal: Boolean = false,
    val minContextWindow: Int? = null,
    val requiredCapabilities: Set<Capability> = emptySet()
)

enum class RoutingPolicy {
    BALANCED,
    QUALITY_FIRST,
    COST_OPTIMIZED,
    SPEED_FIRST,
    PRIVACY_FIRST
}

data class RoutingDecision(
    val model: Model,
    val reason: String,
    val alternatives: List<ScoredModel>,
    val estimatedCost: Double? = null
)
```

### Model Adapter Interface

```kotlin
// forge-core/src/main/kotlin/dev/forge/models/ModelAdapter.kt

package dev.forge.models

import kotlinx.coroutines.flow.Flow

interface ModelAdapter {
    val modelId: String
    val provider: String
    
    /**
     * Stream completion tokens
     */
    suspend fun complete(
        messages: List<Message>,
        systemPrompt: String? = null,
        temperature: Double = 0.7,
        maxTokens: Int? = null
    ): Flow<String>
    
    /**
     * Get full completion (non-streaming)
     */
    suspend fun completeSync(
        messages: List<Message>,
        systemPrompt: String? = null,
        temperature: Double = 0.7,
        maxTokens: Int? = null
    ): CompletionResult
    
    /**
     * Health check
     */
    suspend fun healthCheck(): HealthStatus
    
    /**
     * Count tokens (for cost estimation)
     */
    fun countTokens(text: String): Int
}

data class Message(
    val role: Role,
    val content: String
)

enum class Role { USER, ASSISTANT, SYSTEM }

data class CompletionResult(
    val content: String,
    val inputTokens: Int,
    val outputTokens: Int,
    val latencyMs: Long,
    val model: String
)

data class HealthStatus(
    val healthy: Boolean,
    val latencyMs: Long,
    val message: String? = null
)
```

### Anthropic Adapter

```kotlin
// forge-core/src/main/kotlin/dev/forge/models/AnthropicAdapter.kt

package dev.forge.models

import io.ktor.client.*
import io.ktor.client.request.*
import io.ktor.client.statement.*
import io.ktor.http.*
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.flow
import kotlinx.serialization.json.*

class AnthropicAdapter(
    private val client: HttpClient,
    private val apiKey: String,
    override val modelId: String
) : ModelAdapter {
    
    override val provider = "anthropic"
    
    override suspend fun complete(
        messages: List<Message>,
        systemPrompt: String?,
        temperature: Double,
        maxTokens: Int?
    ): Flow<String> = flow {
        val response = client.post("https://api.anthropic.com/v1/messages") {
            header("x-api-key", apiKey)
            header("anthropic-version", "2023-06-01")
            contentType(ContentType.Application.Json)
            setBody(buildJsonObject {
                put("model", modelId)
                put("max_tokens", maxTokens ?: 4096)
                put("temperature", temperature)
                put("stream", true)
                systemPrompt?.let { put("system", it) }
                putJsonArray("messages") {
                    messages.forEach { msg ->
                        addJsonObject {
                            put("role", msg.role.name.lowercase())
                            put("content", msg.content)
                        }
                    }
                }
            })
        }
        
        // Parse SSE stream
        response.bodyAsChannel().let { channel ->
            val buffer = StringBuilder()
            while (!channel.isClosedForRead) {
                val line = channel.readUTF8Line() ?: break
                if (line.startsWith("data: ")) {
                    val data = line.removePrefix("data: ")
                    if (data == "[DONE]") break
                    
                    val json = Json.parseToJsonElement(data).jsonObject
                    val delta = json["delta"]?.jsonObject
                    val text = delta?.get("text")?.jsonPrimitive?.contentOrNull
                    text?.let { emit(it) }
                }
            }
        }
    }
    
    override suspend fun healthCheck(): HealthStatus {
        return try {
            val start = System.currentTimeMillis()
            completeSync(
                messages = listOf(Message(Role.USER, "Hi")),
                maxTokens = 1
            )
            val latency = System.currentTimeMillis() - start
            HealthStatus(healthy = true, latencyMs = latency)
        } catch (e: Exception) {
            HealthStatus(healthy = false, latencyMs = -1, message = e.message)
        }
    }
    
    override fun countTokens(text: String): Int {
        // Approximate: ~4 chars per token for English
        return (text.length / 4).coerceAtLeast(1)
    }
}
```

### Knowledge Retriever

```kotlin
// forge-core/src/main/kotlin/dev/forge/memory/Retriever.kt

package dev.forge.memory

import dev.forge.db.repositories.KnowledgeRepository

class Retriever(
    private val repository: KnowledgeRepository,
    private val embedder: Embedder
) {
    /**
     * Semantic search via MongoDB Atlas Vector Search + VoyageAI
     */
    suspend fun search(
        query: String,
        projects: List<String>? = null,
        limit: Int = 5,
        minSimilarity: Double = 0.7
    ): List<RetrievalResult> {
        // 1. Embed query with VoyageAI
        val queryEmbedding = embedder.embed(query)

        // 2. Vector search via Atlas Vector Search ($vectorSearch aggregation)
        return repository.searchByVector(
            embedding = queryEmbedding,
            projects = projects,
            limit = limit,
            minSimilarity = minSimilarity
        )
    }

    /**
     * Hybrid search: Atlas Vector Search (semantic) + Atlas text search (keyword)
     */
    suspend fun hybridSearch(
        query: String,
        projects: List<String>? = null,
        limit: Int = 5
    ): List<RetrievalResult> {
        // Semantic results (Atlas Vector Search)
        val semanticResults = search(query, projects, limit * 2)

        // Full-text search results (Atlas text index)
        val keywordResults = repository.searchByKeyword(query, projects, limit * 2)

        // Merge and re-rank (reciprocal rank fusion)
        return mergeResults(semanticResults, keywordResults, limit)
    }

    private fun mergeResults(
        semantic: List<RetrievalResult>,
        keyword: List<RetrievalResult>,
        limit: Int
    ): List<RetrievalResult> {
        val scores = mutableMapOf<String, Double>()
        val k = 60.0 // RRF constant

        semantic.forEachIndexed { i, result ->
            scores[result.id] = scores.getOrDefault(result.id, 0.0) + 1.0 / (k + i)
        }

        keyword.forEachIndexed { i, result ->
            scores[result.id] = scores.getOrDefault(result.id, 0.0) + 1.0 / (k + i)
        }

        val allResults = (semantic + keyword).distinctBy { it.id }

        return allResults
            .sortedByDescending { scores[it.id] }
            .take(limit)
    }
}

data class RetrievalResult(
    val id: String,
    val content: String,
    val project: String,
    val filename: String?,
    val similarity: Double,
    val metadata: Map<String, Any>
)
```

---

## Build Configuration

### Root build.gradle.kts

```kotlin
// build.gradle.kts

plugins {
    kotlin("jvm") version "2.0.0" apply false
    kotlin("plugin.serialization") version "2.0.0" apply false
}

allprojects {
    group = "dev.forge"
    version = "0.1.0"
    
    repositories {
        mavenCentral()
    }
}

subprojects {
    apply(plugin = "org.jetbrains.kotlin.jvm")
    apply(plugin = "org.jetbrains.kotlin.plugin.serialization")
    
    dependencies {
        // Coroutines
        implementation("org.jetbrains.kotlinx:kotlinx-coroutines-core:1.8.0")
        
        // Serialization
        implementation("org.jetbrains.kotlinx:kotlinx-serialization-json:1.6.3")
        
        // Testing
        testImplementation(kotlin("test"))
        testImplementation("org.jetbrains.kotlinx:kotlinx-coroutines-test:1.8.0")
    }
    
    tasks.withType<org.jetbrains.kotlin.gradle.tasks.KotlinCompile> {
        kotlinOptions {
            jvmTarget = "21"
            freeCompilerArgs = listOf("-Xcontext-receivers")
        }
    }
}
```

### forge-core/build.gradle.kts

```kotlin
// forge-core/build.gradle.kts

plugins {
    kotlin("jvm")
    kotlin("plugin.serialization")
}

dependencies {
    // Ktor Client (for API calls)
    implementation("io.ktor:ktor-client-core:2.3.8")
    implementation("io.ktor:ktor-client-cio:2.3.8")
    implementation("io.ktor:ktor-client-content-negotiation:2.3.8")
    implementation("io.ktor:ktor-serialization-kotlinx-json:2.3.8")
    
    // Database - Exposed
    implementation("org.jetbrains.exposed:exposed-core:0.47.0")
    implementation("org.jetbrains.exposed:exposed-dao:0.47.0")
    implementation("org.jetbrains.exposed:exposed-jdbc:0.47.0")
    implementation("org.jetbrains.exposed:exposed-java-time:0.47.0")
    implementation("org.jetbrains.exposed:exposed-json:0.47.0")
    
    // PostgreSQL
    implementation("org.postgresql:postgresql:42.7.1")
    implementation("com.zaxxer:HikariCP:5.1.0")
    
    // pgvector
    implementation("com.pgvector:pgvector:0.1.4")

    // MongoDB
    implementation("org.mongodb:mongodb-driver-kotlin-coroutine:5.0.0")
    implementation("org.mongodb:bson-kotlinx:5.0.0")

    // Redis - Lettuce
    implementation("io.lettuce:lettuce-core:6.3.1.RELEASE")
    
    // DI - Koin
    implementation("io.insert-koin:koin-core:3.5.3")
    
    // Config
    implementation("com.sksamuel.hoplite:hoplite-core:2.7.5")
    implementation("com.sksamuel.hoplite:hoplite-yaml:2.7.5")
    
    // Logging
    implementation("io.github.microutils:kotlin-logging-jvm:3.0.5")
    implementation("ch.qos.logback:logback-classic:1.4.14")
}
```

---

## Docker Compose (Dev Environment)

```yaml
# docker/docker-compose.yaml

version: '3.8'

services:
  postgres:
    image: pgvector/pgvector:pg16
    container_name: forge-postgres
    environment:
      POSTGRES_USER: forge
      POSTGRES_PASSWORD: forge_dev_password
      POSTGRES_DB: forge_os
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data
      - ./init.sql:/docker-entrypoint-initdb.d/init.sql
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U forge -d forge_os"]
      interval: 5s
      timeout: 5s
      retries: 5

  redis:
    image: redis:7-alpine
    container_name: forge-redis
    ports:
      - "6379:6379"
    volumes:
      - redis_data:/data
    command: redis-server --appendonly yes
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 5s
      retries: 5

  mongodb:
    image: mongodb/mongodb-atlas-local:latest
    container_name: forge-mongodb
    environment:
      MONGODB_INITDB_ROOT_USERNAME: forge
      MONGODB_INITDB_ROOT_PASSWORD: forge_dev_password
    ports:
      - "27017:27017"
    volumes:
      - mongodb_data:/data/db
    healthcheck:
      test: ["CMD", "mongosh", "--eval", "db.adminCommand('ping')"]
      interval: 5s
      timeout: 5s
      retries: 5

  # Optional: Ollama for local models
  ollama:
    image: ollama/ollama:latest
    container_name: forge-ollama
    ports:
      - "11434:11434"
    volumes:
      - ollama_data:/root/.ollama
    deploy:
      resources:
        reservations:
          devices:
            - capabilities: [gpu]  # If NVIDIA GPU available

volumes:
  postgres_data:
  mongodb_data:
  redis_data:
  ollama_data:
```

---

## Summary: Stack Comparison

| Component | Stepping Stone (Python) | Track B (Kotlin) |
|-----------|------------------------|------------------|
| **Language** | Python 3.12 | Kotlin 2.0 (JVM 21) |
| **HTTP** | — | Ktor |
| **Async** | asyncio | Coroutines |
| **Document DB** | MongoDB | MongoDB (same, migrated) |
| **Vector Search** | Atlas Vector Search + VoyageAI | Atlas Vector Search + VoyageAI (same) |
| **Relational DB** | — | PostgreSQL 16+ |
| **Relational Vectors** | — | pgvector (secondary) |
| **Cache** | — | Redis (Lettuce) |
| **CLI** | — | Clikt |
| **DI** | — | Koin |
| **Serialization** | Pydantic | kotlinx.serialization |

### Why Kotlin + PostgreSQL + MongoDB?

1. **Type Safety** — Catch errors at compile time, not runtime
2. **Performance** — JVM optimizations, GraalVM native-image option
3. **Ecosystem** — Mature libraries (Ktor, Exposed, Koin)
4. **Right DB for the Job** — PostgreSQL for relational data (models, routing, costs); MongoDB for documents, graphs, and vector search (conversations, archives, registries)
5. **Continuity** — MongoDB + VoyageAI carries through from the stepping stone, no data migration needed for document/vector workloads
6. **Proven Vector Search** — Atlas Vector Search with VoyageAI embeddings is already validated in the stepping stone codebase
7. **Operational** — Both PostgreSQL and MongoDB are battle-tested with excellent tooling
8. **Coroutines** — Structured concurrency, both DB drivers support coroutines natively

---

Ready to proceed with implementation?
