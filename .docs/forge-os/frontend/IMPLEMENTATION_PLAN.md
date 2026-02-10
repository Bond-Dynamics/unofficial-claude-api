# Forge OS Mission Control Dashboard — Implementation Plan

**Date:** 2026-02-09
**Status:** Approved for implementation
**References:** `FORGE_OS_MISSION_CONTROL_PROJECT_SPEC.md`, `forge-os-architecture.md`, `FORGE_OS_IMPLEMENTATION_GUIDE.md` Phase 6

---

## 1. Context & Motivation

Forge OS has a fully operational backend: 229 conversations across 15 projects, 138 decisions, threads, lineage edges, compression registries, priming blocks, expedition flags, conflict detection, and vector search — all in MongoDB (`claude_search` database) with a Python `vectordb/` module exposing 60+ functions. But there is no visual interface. Everything is accessed through CLI scripts (`trace_lineage.py`, `search.py`, `prepare_compression.py`, etc.).

The Forge OS architecture docs already envision this dashboard:
- `FORGE_OS_MISSION_CONTROL_PROJECT_SPEC.md` — defines a Mission Control dashboard with progress bars, task tracking, milestone gates, and blocker alerts
- `FORGE_OS_IMPLEMENTATION_GUIDE.md` Phase 6 — lists "Web UI" as the polish phase deliverable
- `FORGE_OS_LOCAL_ARCHITECTURE_KOTLIN.md` — mentions `forge-web/` module with "Visual chat" UI
- `forge-os-architecture.md` — describes the full Layer 0-4 stack, with the dashboard as the human interface to the semantic DAG

**Decision:** Next.js + React, local + GCE mirror, lineage graph AND project overview dashboard built together.

---

## 2. System Architecture

```
+-----------------------------------------------------------+
|  Next.js Frontend (port 3000)                              |
|  +-- /                    -> Project overview dashboard    |
|  +-- /projects/[name]     -> Project detail + decisions    |
|  +-- /lineage             -> Full lineage DAG graph        |
|  +-- /lineage/[id]        -> Single conversation trace     |
|  +-- /decisions           -> Decision registry + conflicts |
|  +-- /threads             -> Thread registry + stale warn  |
|  +-- /search              -> Semantic vector search        |
|  +-- /api/*               -> Next.js API routes (proxy)    |
+---------------------------+-------------------------------+
                            | HTTP (localhost)
+---------------------------+-------------------------------+
|  Python API Server (FastAPI, port 8000)                    |
|  Wraps vectordb/* query functions as REST endpoints        |
|  No new logic - pure passthrough to existing functions     |
+---------------------------+-------------------------------+
                            | pymongo
+---------------------------+-------------------------------+
|  MongoDB (claude-vectordb container, port 27017)           |
|  Database: claude_search                                   |
|  17 collections, 229 conversations, vector indexes         |
+-----------------------------------------------------------+
```

### Why a separate Python API instead of Next.js API routes directly to MongoDB?

- The `vectordb/` module has 60+ functions with complex query logic (vector search pipelines, conflict detection, hop counting, UUIDv8 derivation, VoyageAI embedding). Rewriting in JS would be massive duplication.
- FastAPI wraps the existing Python functions with zero new logic. Each endpoint is 5-10 lines.
- Next.js API routes call FastAPI. The Python API is the single source of truth.
- The vectordb module handles its own MongoDB connection via `vectordb.db.get_database()` with URI `mongodb://localhost:27017/?directConnection=true` and database name `claude_search`.

---

## 3. Existing Backend API Surface (Complete Reference)

### 3.1 Database Configuration

From `vectordb/config.py`:

```python
MONGODB_URI = "mongodb://localhost:27017/?directConnection=true"
DATABASE_NAME = "claude_search"
EMBEDDING_DIMENSIONS = 1024  # VoyageAI voyage-3
STALE_MAX_HOPS = 3
STALE_MAX_DAYS = 30
DECISION_CONFLICT_SIMILARITY_THRESHOLD = 0.85
```

### 3.2 Collections (17 total)

| Collection | Config Constant | Layer | Purpose |
|-----------|----------------|-------|---------|
| `message_embeddings` | `COLLECTION_MESSAGES` | 0 | Individual message embeddings |
| `conversation_embeddings` | `COLLECTION_CONVERSATIONS` | 0 | Conversation-level embeddings |
| `document_embeddings` | `COLLECTION_DOCUMENTS` | 0 | Document embeddings |
| `published_artifacts` | `COLLECTION_PUBLISHED_ARTIFACTS` | 0 | Published code/text artifacts |
| `code_sessions` | `COLLECTION_CODE_SESSIONS` | 0 | Code session records |
| `code_repos` | `COLLECTION_CODE_REPOS` | 0 | Repository metadata |
| `patterns` | `COLLECTION_PATTERNS` | 1 | Learned patterns |
| `scratchpad` | `COLLECTION_SCRATCHPAD` | 1 | Temporary context (TTL) |
| `archive` | `COLLECTION_ARCHIVE` | 1 | Archived documents |
| `memory_events` | `COLLECTION_EVENTS` | 1 | System events (TTL 90d) |
| `conversation_registry` | `COLLECTION_CONVERSATION_REGISTRY` | 2 | UUIDv8 identity mapping |
| `thread_registry` | `COLLECTION_THREAD_REGISTRY` | 2 | Thread lifecycle tracking |
| `decision_registry` | `COLLECTION_DECISION_REGISTRY` | 2 | Decision lifecycle + embeddings |
| `lineage_edges` | `COLLECTION_LINEAGE_EDGES` | 2 | DAG edges between conversations |
| `compression_registry` | `COLLECTION_COMPRESSION_REGISTRY` | 2 | Compression event tracking |
| `priming_registry` | `COLLECTION_PRIMING_REGISTRY` | 2.5 | Expedition priming blocks |
| `expedition_flags` | `COLLECTION_EXPEDITION_FLAGS` | 2.5 | Expedition bookmark flags |

### 3.3 All Exported Functions (from `vectordb/__init__.py`)

#### Conversation Registry (`vectordb/conversation_registry.py`)

| Function | Signature | Returns | Dashboard Use |
|----------|-----------|---------|---------------|
| `list_projects()` | `(db=None)` | `[{project_name, project_uuid, conversation_count, earliest_at, latest_at}]` sorted by count desc | Home dashboard project list |
| `list_project_conversations(project_name)` | `(project_name, db=None)` | `[{uuid, source_id, project_name, project_uuid, conversation_name, summary, created_at, created_at_ms}]` sorted by created_at_ms asc | Project detail conversations tab |
| `get_conversation(source_id)` | `(source_id, db=None)` | Single conversation doc or `None` | Conversation lookup |
| `get_conversation_by_uuid(conv_uuid)` | `(conv_uuid, db=None)` | Single conversation doc or `None` | UUID-based lookup |
| `resolve_id(identifier)` | `(identifier, db=None)` | Conversation doc or `None`. Tries: exact source_id, exact uuid, prefix match (4+ chars), case-insensitive name substring | Universal ID resolver |
| `register_conversation(...)` | `(source_id, project_name, conversation_name=None, created_at=None, summary=None, db=None)` | `{action, uuid, project_uuid}` | Write-only (not needed for dashboard) |

#### Decision Registry (`vectordb/decision_registry.py`)

| Function | Signature | Returns | Dashboard Use |
|----------|-----------|---------|---------------|
| `get_active_decisions(project)` | `(project, db=None)` | `[{uuid, local_id, text, text_hash, project, epistemic_tier, status, dependents, dependencies, conflicts_with, superseded_by, rationale, hops_since_validated, last_validated, created_at, updated_at}]` sorted by epistemic_tier desc. Excludes `_id` and `embedding`. | Decisions page, project detail |
| `get_stale_decisions(project)` | `(project, max_hops=None, max_days=None, db=None)` | Same shape, filtered to stale (hops >= 3 OR last_validated > 30 days ago) | Stale alerts |
| `find_similar_decisions(text, project)` | `(text, project, limit=5, threshold=None, db=None)` | Decisions with `similarity` field | Search results |
| `supersede_decision(uuid, by_uuid)` | Write-only | | |
| `increment_decision_hops(project)` | Write-only | | |
| `upsert_decision(...)` | Write-only | | |

#### Thread Registry (`vectordb/thread_registry.py`)

| Function | Signature | Returns | Dashboard Use |
|----------|-----------|---------|---------------|
| `get_active_threads(project)` | `(project, db=None)` | `[{uuid, local_id, title, status, project, priority, blocked_by, resolution, epistemic_tier, hops_since_validated, last_validated, created_at, updated_at}]` sorted by priority (high first) then updated_at | Threads page, project detail |
| `get_stale_threads(project)` | `(project, max_hops=None, max_days=None, db=None)` | Same shape, filtered to stale | Stale alerts |
| `resolve_thread(uuid, resolution)` | Write-only | | |
| `increment_thread_hops(project)` | Write-only | | |
| `upsert_thread(...)` | Write-only | | |

#### Lineage (`vectordb/lineage.py`)

| Function | Signature | Returns | Dashboard Use |
|----------|-----------|---------|---------------|
| `get_full_graph(project=None)` | `(project=None, db=None)` | `[{edge_uuid, source_conversation, target_conversation, source_project, target_project, compression_tag, decisions_carried, decisions_dropped, threads_carried, threads_resolved, created_at, updated_at}]` sorted by created_at asc. If `project` provided, filters to edges where either source or target matches. | Lineage DAG graph |
| `trace_conversation(conversation_id)` | `(conversation_id, depth=10, db=None)` | `{ancestors: [{edge}], descendants: [{edge}], root: uuid, leaves: [uuid], conversations: set, projects: set, cross_project: bool}` | Conversation trace page |
| `get_ancestors(conversation_id)` | `(conversation_id, depth=5, db=None)` | `[{edge}]` newest to oldest | Internal to trace |
| `get_descendants(conversation_id)` | `(conversation_id, depth=5, db=None)` | `[{edge}]` oldest to newest | Internal to trace |
| `get_lineage_chain(compression_tag)` | `(compression_tag, db=None)` | `[{edge}]` sorted by created_at | Compression detail |
| `add_edge(...)` | Write-only | | |

#### Conflicts (`vectordb/conflicts.py`)

| Function | Signature | Returns | Dashboard Use |
|----------|-----------|---------|---------------|
| `detect_conflicts(text, tier, project)` | `(decision_text, decision_tier, project, exclude_uuid=None, db=None)` | `[{existing_uuid, existing_text, signal, similarity, shared_entities, severity}]` | Conflict detection (read via decisions' `conflicts_with` field) |
| `register_conflict(uuid_a, uuid_b, signal)` | Write-only | | |

#### Compression Registry (`vectordb/compression_registry.py`)

| Function | Signature | Returns | Dashboard Use |
|----------|-----------|---------|---------------|
| `list_compressions(project)` | `(project, since=None, limit=50, db=None)` | `[{compression_tag, project, source_conversation, target_conversations, decisions_captured, threads_captured, artifacts_captured, checksum, metadata, created_at, updated_at}]` newest first | Project detail compressions tab |
| `get_compression(tag)` | `(compression_tag, db=None)` | Single doc or `None` | Compression detail |
| `verify_checksum(tag, text)` | Verification utility | | |
| `compute_checksum(text)` | Utility | | |
| `register_compression(...)` | Write-only | | |

#### Priming Registry (`vectordb/priming_registry.py`)

| Function | Signature | Returns | Dashboard Use |
|----------|-----------|---------|---------------|
| `list_priming_blocks(project)` | `(project, db=None)` | `[{uuid, territory_name, territory_keys, territory_keys_text, content, content_hash, project, source_expeditions, confidence_floor, findings_count, status, created_at, updated_at}]` no embedding, sorted by updated_at desc | Project detail priming tab |
| `get_priming_block(territory, project, project_uuid)` | `(territory_name, project, project_uuid, db=None)` | Single doc or `None` | Priming detail |
| `find_relevant_priming(topic, project)` | `(topic_text, project=None, limit=3, threshold=None, db=None)` | Blocks with `similarity` | Search results |
| `upsert_priming_block(...)` | Write-only | | |
| `deactivate_priming_block(uuid)` | Write-only | | |

#### Expedition Flags (`vectordb/expedition_flags.py`)

| Function | Signature | Returns | Dashboard Use |
|----------|-----------|---------|---------------|
| `get_all_flags(project)` | `(project, include_compiled=False, db=None)` | `[{uuid, description, project, conversation_id, category, context, status, compiled_into, created_at, updated_at}]` newest first | Project detail flags tab |
| `get_pending_flags(project)` | `(project, db=None)` | Pending only, newest first | Alerts section |
| `get_flags_by_category(project, category)` | `(project, category, db=None)` | Filtered by category | Filter UI |
| `plant_flag(...)` | Write-only | | |
| `mark_flag_compiled(uuid, into)` | Write-only | | |
| `delete_flag(uuid)` | Write-only | | |

#### Vector Search (`vectordb/vector_store.py`)

| Function | Signature | Returns | Dashboard Use |
|----------|-----------|---------|---------------|
| `vector_search(query, collection_name, ...)` | `(query, collection_name=COLLECTION_MESSAGES, limit=5, content_type=None, sender=None, project_name=None, is_starred=None, threshold=0.3, db=None)` | `[{text, score, content_type, ...}]` sorted by score desc. Uses VoyageAI `embed_query()` for query embedding. | Search page |
| `vector_store(...)` | Write-only | | |

#### Other Modules (not directly needed for dashboard)

- **Patterns** (`vectordb/patterns.py`): `pattern_store()`, `pattern_match()` — ML pattern matching
- **Context** (`vectordb/context.py`): `context_load()`, `context_flush()`, `context_resize()` — session context
- **Scratchpad** (`vectordb/scratchpad.py`): CRUD for temporary key-value pairs
- **Archive** (`vectordb/archive.py`): `archive_store()`, `archive_retrieve()`, `forget()` — document archival
- **Events** (`vectordb/events.py`): `emit_event()` — event bus
- **UUIDv8** (`vectordb/uuidv8.py`): Deterministic ID derivation functions
- **Embeddings** (`vectordb/embeddings.py`): `embed_texts()`, `embed_query()` — VoyageAI voyage-3 (1024 dims)

---

## 4. Files to Create

```
web/                                    # Next.js app (new directory)
  package.json                          # Dependencies: next, react, react-force-graph-2d, etc.
  next.config.js                        # API proxy to FastAPI
  tsconfig.json                         # TypeScript config
  tailwind.config.ts                    # Dark theme config
  postcss.config.js                     # PostCSS for Tailwind

  app/
    layout.tsx                          # Root layout with sidebar nav
    page.tsx                            # Project overview dashboard (home)
    globals.css                         # Tailwind base styles + dark theme

    projects/
      [name]/
        page.tsx                        # Project detail: decisions, threads, conversations

    lineage/
      page.tsx                          # Full lineage DAG graph
      [id]/
        page.tsx                        # Single conversation trace

    decisions/
      page.tsx                          # Decision registry with conflict indicators

    threads/
      page.tsx                          # Thread registry with stale warnings

    search/
      page.tsx                          # Semantic search interface

  components/
    Sidebar.tsx                         # Navigation sidebar
    ProjectCard.tsx                     # Project summary card (clickable)
    DecisionTable.tsx                   # Decision list with tier badges
    ThreadTable.tsx                     # Thread list with status/priority
    LineageGraph.tsx                    # react-force-graph-2d DAG visualization
    ConversationTrace.tsx               # Ancestor/descendant chain view
    ConflictBadge.tsx                   # Conflict indicator component
    StaleBadge.tsx                      # Stale warning indicator
    EpistemicTierBadge.tsx              # Tier color badge (green/amber/red)
    SearchBar.tsx                       # Vector search input + scope toggle
    StatsCard.tsx                       # Metric card (count + label)

  lib/
    api.ts                              # Fetch wrapper for Python API
    types.ts                            # TypeScript interfaces for all API shapes

scripts/
  api_server.py                         # FastAPI server wrapping vectordb/*
```

### Files to Edit

```
scripts/start_mongodb.sh                # Add note about API server companion
```

---

## 5. Implementation Phases

### Phase 1: Python FastAPI Server (`scripts/api_server.py`)

**Goal:** Wrap existing `vectordb/` functions as REST endpoints. Zero new query logic.

**Dependencies:** `pip install fastapi uvicorn` (added to existing `requirements.txt`)

**Estimated size:** ~250 lines

#### Endpoint Table

| Method | Path | Wraps | Parameters | Returns |
|--------|------|-------|-----------|---------|
| GET | `/api/projects` | `list_projects()` | — | `[{project_name, project_uuid, conversation_count, earliest_at, latest_at}]` |
| GET | `/api/projects/{name}/conversations` | `list_project_conversations(name)` | `name` path param | `[{uuid, source_id, conversation_name, summary, created_at, created_at_ms}]` |
| GET | `/api/projects/{name}/decisions` | `get_active_decisions(name)` | `name` path param | `[{uuid, local_id, text, epistemic_tier, status, conflicts_with, hops_since_validated, ...}]` |
| GET | `/api/projects/{name}/threads` | `get_active_threads(name)` | `name` path param | `[{uuid, local_id, title, status, priority, blocked_by, ...}]` |
| GET | `/api/projects/{name}/stale` | `get_stale_decisions(name) + get_stale_threads(name)` | `name` path param | `{decisions: [...], threads: [...]}` |
| GET | `/api/projects/{name}/flags` | `get_all_flags(name)` | `name` path param | `[{uuid, description, category, status, ...}]` |
| GET | `/api/projects/{name}/priming` | `list_priming_blocks(name)` | `name` path param | `[{uuid, territory_name, territory_keys, content, ...}]` |
| GET | `/api/projects/{name}/compressions` | `list_compressions(name)` | `name` path param, optional `limit` query | `[{compression_tag, source_conversation, decisions_captured, ...}]` |
| GET | `/api/decisions` | Aggregated `get_active_decisions()` across all projects | — | `[{...}]` grouped/sorted |
| GET | `/api/decisions/conflicts` | Query decision_registry where `conflicts_with` non-empty | — | `[{uuid, text, conflicts_with, ...}]` |
| GET | `/api/threads` | Aggregated `get_active_threads()` across all projects | — | `[{...}]` grouped/sorted |
| GET | `/api/lineage/graph` | `get_full_graph(project?)` | Optional `project` query param | `{nodes: [...], edges: [...]}` (transformed for graph rendering) |
| GET | `/api/lineage/trace/{id}` | `resolve_id(id)` + `trace_conversation(uuid)` | `id` path param | `{conversation, ancestors, descendants, root, leaves, cross_project}` |
| GET | `/api/conversations/{id}` | `resolve_id(id)` | `id` path param | Single conversation doc |
| GET | `/api/search` | `vector_search(query, ...)` | `q`, `scope` (conversations/messages/decisions), `limit` query params | `[{text, score, ...}]` |
| GET | `/api/stats` | Aggregate counts across collections | — | `{conversations, projects, decisions, threads, edges, flags, compressions, priming_blocks}` |

#### CORS Configuration

```python
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["GET"],
    allow_headers=["*"],
)
```

#### Graph Endpoint Transformation

The `/api/lineage/graph` endpoint must transform the raw edge list into a nodes + edges format suitable for react-force-graph-2d:

```python
@app.get("/api/lineage/graph")
def get_lineage_graph(project: str = None):
    edges = get_full_graph(project=project)

    # Build node set from edges
    node_ids = set()
    for edge in edges:
        node_ids.add(edge["source_conversation"])
        node_ids.add(edge["target_conversation"])

    # Enrich nodes with conversation metadata
    nodes = []
    for nid in node_ids:
        conv = get_conversation_by_uuid(nid)
        nodes.append({
            "id": nid,
            "name": conv["conversation_name"] if conv else nid[:8],
            "project": conv["project_name"] if conv else "",
            "created_at": conv.get("created_at") if conv else None,
        })

    graph_edges = [
        {
            "source": e["source_conversation"],
            "target": e["target_conversation"],
            "compression_tag": e.get("compression_tag", ""),
            "cross_project": e.get("source_project", "") != e.get("target_project", ""),
            "decisions_carried": len(e.get("decisions_carried", [])),
            "threads_carried": len(e.get("threads_carried", [])),
        }
        for e in edges
    ]

    return {"nodes": nodes, "edges": graph_edges}
```

#### Stats Endpoint

```python
@app.get("/api/stats")
def get_stats():
    db = get_database()
    return {
        "conversations": db["conversation_registry"].count_documents({}),
        "projects": len(list_projects()),
        "decisions": db["decision_registry"].count_documents({"status": "active"}),
        "threads": db["thread_registry"].count_documents({"status": {"$ne": "resolved"}}),
        "edges": db["lineage_edges"].count_documents({}),
        "flags": db["expedition_flags"].count_documents({"status": "pending"}),
        "compressions": db["compression_registry"].count_documents({}),
        "priming_blocks": db["priming_registry"].count_documents({"status": "active"}),
    }
```

#### All-Projects Aggregation

For `/api/decisions` and `/api/threads` (cross-project views), iterate over `list_projects()` and call the per-project functions, then flatten:

```python
@app.get("/api/decisions")
def get_all_decisions():
    projects = list_projects()
    all_decisions = []
    for p in projects:
        decisions = get_active_decisions(p["project_name"])
        all_decisions.extend(decisions)
    return all_decisions

@app.get("/api/decisions/conflicts")
def get_conflicting_decisions():
    db = get_database()
    return list(db["decision_registry"].find(
        {"status": "active", "conflicts_with": {"$ne": []}},
        {"_id": 0, "embedding": 0},
    ))
```

#### Serialization

MongoDB documents may contain `datetime` objects and `ObjectId`s. Use FastAPI's `JSONResponse` with a custom encoder:

```python
from bson import ObjectId
from datetime import datetime
import json

class MongoEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, ObjectId):
            return str(obj)
        if isinstance(obj, datetime):
            return obj.isoformat()
        if isinstance(obj, set):
            return list(obj)
        return super().default(obj)
```

#### Startup

```bash
cd /path/to/project
python scripts/api_server.py
# or: uvicorn scripts.api_server:app --port 8000 --reload
```

---

### Phase 2: Next.js Project Scaffold

**Goal:** Create the Next.js app with routing, layout, and API client.

#### Setup Commands

```bash
cd web
npx create-next-app@latest . --typescript --tailwind --app --no-src-dir --no-import-alias
npm install react-force-graph-2d d3 lucide-react
```

#### `next.config.js` — API Proxy

```javascript
/** @type {import('next').NextConfig} */
const nextConfig = {
  async rewrites() {
    return [
      {
        source: '/api/:path*',
        destination: 'http://localhost:8000/api/:path*',
      },
    ]
  },
}
module.exports = nextConfig
```

This means all `/api/*` calls from the frontend transparently proxy to FastAPI. No CORS issues in production-like setup.

#### `lib/types.ts` — TypeScript Interfaces

```typescript
export interface Project {
  project_name: string
  project_uuid: string
  conversation_count: number
  earliest_at: number
  latest_at: number
}

export interface Conversation {
  uuid: string
  source_id: string
  project_name: string
  project_uuid: string
  conversation_name: string
  summary: string
  created_at: string
  created_at_ms: number
  updated_at: string
}

export interface Decision {
  uuid: string
  local_id: string
  text: string
  project: string
  epistemic_tier: number | null
  status: string
  conflicts_with: string[]
  superseded_by: string | null
  dependents: string[]
  dependencies: string[]
  rationale: string
  hops_since_validated: number
  last_validated: string
  created_at: string
  updated_at: string
}

export interface Thread {
  uuid: string
  local_id: string
  title: string
  status: string  // "open" | "resolved" | "blocked"
  project: string
  priority: string  // "high" | "medium" | "low"
  blocked_by: string[]
  resolution: string
  epistemic_tier: number | null
  hops_since_validated: number
  last_validated: string
  created_at: string
  updated_at: string
}

export interface LineageEdge {
  edge_uuid: string
  source_conversation: string
  target_conversation: string
  source_project: string
  target_project: string
  compression_tag: string
  decisions_carried: string[]
  decisions_dropped: string[]
  threads_carried: string[]
  threads_resolved: string[]
  created_at: string
  updated_at: string
}

export interface GraphNode {
  id: string
  name: string
  project: string
  created_at: string | null
}

export interface GraphEdge {
  source: string
  target: string
  compression_tag: string
  cross_project: boolean
  decisions_carried: number
  threads_carried: number
}

export interface GraphData {
  nodes: GraphNode[]
  edges: GraphEdge[]
}

export interface ConversationTrace {
  conversation: Conversation
  ancestors: LineageEdge[]
  descendants: LineageEdge[]
  root: string
  leaves: string[]
  conversations: string[]
  projects: string[]
  cross_project: boolean
}

export interface Compression {
  compression_tag: string
  project: string
  source_conversation: string
  target_conversations: string[]
  decisions_captured: string[]
  threads_captured: string[]
  artifacts_captured: string[]
  checksum: string
  metadata: Record<string, unknown>
  created_at: string
  updated_at: string
}

export interface PrimingBlock {
  uuid: string
  territory_name: string
  territory_keys: string[]
  territory_keys_text: string
  content: string
  project: string
  source_expeditions: string[]
  confidence_floor: number
  findings_count: Record<string, number>
  status: string
  created_at: string
  updated_at: string
}

export interface ExpeditionFlag {
  uuid: string
  description: string
  project: string
  conversation_id: string
  category: string
  context: string
  status: string
  compiled_into: string | null
  created_at: string
  updated_at: string
}

export interface Stats {
  conversations: number
  projects: number
  decisions: number
  threads: number
  edges: number
  flags: number
  compressions: number
  priming_blocks: number
}

export interface SearchResult {
  text: string
  score: number
  content_type: string
  project_name?: string
  conversation_id?: string
  [key: string]: unknown
}

export interface StaleItems {
  decisions: Decision[]
  threads: Thread[]
}
```

#### `lib/api.ts` — Fetch Wrapper

```typescript
const BASE_URL = ''  // Proxied via next.config.js rewrites

async function fetchAPI<T>(path: string, params?: Record<string, string>): Promise<T> {
  const url = new URL(path, 'http://localhost:3000')
  if (params) {
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== '') url.searchParams.set(k, v)
    })
  }

  const res = await fetch(url.toString(), { next: { revalidate: 30 } })
  if (!res.ok) {
    throw new Error(`API error: ${res.status} ${res.statusText}`)
  }
  return res.json()
}

export const api = {
  // Projects
  getProjects: () => fetchAPI<Project[]>('/api/projects'),
  getProjectConversations: (name: string) => fetchAPI<Conversation[]>(`/api/projects/${encodeURIComponent(name)}/conversations`),
  getProjectDecisions: (name: string) => fetchAPI<Decision[]>(`/api/projects/${encodeURIComponent(name)}/decisions`),
  getProjectThreads: (name: string) => fetchAPI<Thread[]>(`/api/projects/${encodeURIComponent(name)}/threads`),
  getProjectStale: (name: string) => fetchAPI<StaleItems>(`/api/projects/${encodeURIComponent(name)}/stale`),
  getProjectFlags: (name: string) => fetchAPI<ExpeditionFlag[]>(`/api/projects/${encodeURIComponent(name)}/flags`),
  getProjectPriming: (name: string) => fetchAPI<PrimingBlock[]>(`/api/projects/${encodeURIComponent(name)}/priming`),
  getProjectCompressions: (name: string) => fetchAPI<Compression[]>(`/api/projects/${encodeURIComponent(name)}/compressions`),

  // Cross-project
  getAllDecisions: () => fetchAPI<Decision[]>('/api/decisions'),
  getConflictingDecisions: () => fetchAPI<Decision[]>('/api/decisions/conflicts'),
  getAllThreads: () => fetchAPI<Thread[]>('/api/threads'),

  // Lineage
  getLineageGraph: (project?: string) => fetchAPI<GraphData>('/api/lineage/graph', project ? { project } : undefined),
  getConversationTrace: (id: string) => fetchAPI<ConversationTrace>(`/api/lineage/trace/${encodeURIComponent(id)}`),

  // Conversations
  getConversation: (id: string) => fetchAPI<Conversation>(`/api/conversations/${encodeURIComponent(id)}`),

  // Search
  search: (q: string, scope?: string, limit?: number) => fetchAPI<SearchResult[]>('/api/search', {
    q,
    ...(scope && { scope }),
    ...(limit && { limit: String(limit) }),
  }),

  // Stats
  getStats: () => fetchAPI<Stats>('/api/stats'),
}
```

#### Root Layout (`app/layout.tsx`)

Dark theme with sidebar navigation:

```
+------------------------------------------+
| MISSION CONTROL (header)                  |
+------+-----------------------------------+
|      |                                    |
| Nav  |  Page Content                      |
| bar  |                                    |
|      |                                    |
| Home |                                    |
| Lin. |                                    |
| Dec. |                                    |
| Thr. |                                    |
| Srch |                                    |
|      |                                    |
+------+-----------------------------------+
```

Navigation items:
- **Overview** (`/`) — Home dashboard
- **Lineage** (`/lineage`) — DAG graph
- **Decisions** (`/decisions`) — Decision registry
- **Threads** (`/threads`) — Thread registry
- **Search** (`/search`) — Semantic search

#### `globals.css`

```css
@tailwind base;
@tailwind components;
@tailwind utilities;

:root {
  --bg-primary: #0a0a0a;
  --bg-secondary: #1a1a2e;
  --bg-card: #16213e;
  --border: #0f3460;
  --accent: #0f3460;
  --text-primary: #e0e0e0;
  --text-secondary: #8892b0;
  --tier-high: #4ade80;      /* green - tier 0.8+ */
  --tier-medium: #fbbf24;    /* amber - tier 0.3-0.7 */
  --tier-low: #ef4444;       /* red - tier <0.3 */
  --status-active: #4ade80;  /* green */
  --status-resolved: #6b7280; /* gray */
  --status-blocked: #ef4444;  /* red */
  --cross-project: #a78bfa;   /* purple */
}

body {
  background: var(--bg-primary);
  color: var(--text-primary);
}
```

---

### Phase 3: Project Overview Dashboard (`app/page.tsx`)

The home view. Server component that fetches data from the API.

#### Layout

```
+===================================================+
|  MISSION CONTROL                                    |
+=====+==============================================+
|     |                                               |
| Nav | [229   ] [15    ] [138   ] [XX   ] [XX  ] [XX]|
|     | convos   projs   decis   thrds   edges  flags |
|     |                                               |
|     | PROJECTS                                      |
|     | +-------------------------------------------+ |
|     | | Cheeky           61 convos | 12 decisions | |
|     | | No Project        59 convos |  0 decisions | |
|     | | The Cartographer  20 convos |  8 decisions | |
|     | | The Transmutation 19 convos |  5 decisions | |
|     | | ...                                       | |
|     | +-------------------------------------------+ |
|     |                                               |
|     | ALERTS                                        |
|     | +-------------------------------------------+ |
|     | | ! 3 stale decisions (5+ hops)             | |
|     | | ! 2 decision conflicts detected           | |
|     | | # 7 pending expedition flags              | |
|     | +-------------------------------------------+ |
+=====+==============================================+
```

#### Data Sources

```
GET /api/stats         -> StatsCard values
GET /api/projects      -> ProjectCard list
GET /api/decisions/conflicts -> Conflict alert count
```

For stale alerts: Iterate projects and sum stale counts. Or add a `/api/alerts` endpoint that aggregates.

#### Components Used

- `StatsCard` — 6 cards across the top (conversations, projects, decisions, threads, edges, flags)
- `ProjectCard` — Clickable card per project. Shows: name, conversation count, decision count. Links to `/projects/[name]`
- Alerts section — Stale decisions, conflicts, pending flags

---

### Phase 4: Project Detail (`app/projects/[name]/page.tsx`)

Drill into a single project. Tab-based layout.

#### Tabs

| Tab | Data Source | Components |
|-----|-----------|-----------|
| **Conversations** | `GET /api/projects/{name}/conversations` | List with name, date, message count |
| **Decisions** | `GET /api/projects/{name}/decisions` | `DecisionTable` with `EpistemicTierBadge`, `ConflictBadge` |
| **Threads** | `GET /api/projects/{name}/threads` | `ThreadTable` with status badges, priority |
| **Compressions** | `GET /api/projects/{name}/compressions` | Timeline of compression events |
| **Priming** | `GET /api/projects/{name}/priming` | Active priming blocks with territory keys |
| **Flags** | `GET /api/projects/{name}/flags` | Pending expedition flags by category |

#### Decision Table Columns

| Column | Source Field | Rendering |
|--------|-------------|-----------|
| ID | `local_id` | Monospace (e.g., `D001`) |
| Decision | `text` | Truncated to 200 chars |
| Tier | `epistemic_tier` | `EpistemicTierBadge`: green (>=0.8), amber (0.3-0.7), red (<0.3), gray (null) |
| Status | `status` | Green badge (active), gray (superseded) |
| Conflicts | `conflicts_with.length` | `ConflictBadge` if > 0 |
| Staleness | `hops_since_validated` | `StaleBadge` if >= STALE_MAX_HOPS (3) |
| Rationale | `rationale` | Tooltip or expandable |

#### Thread Table Columns

| Column | Source Field | Rendering |
|--------|-------------|-----------|
| ID | `local_id` | Monospace (e.g., `T001`) |
| Title | `title` | Full text |
| Status | `status` | Green (open), gray (resolved), red (blocked) |
| Priority | `priority` | High=red, medium=amber, low=gray |
| Blocked By | `blocked_by` | Linked UUIDs |
| Staleness | `hops_since_validated` | `StaleBadge` if >= 3 |

---

### Phase 5: Lineage DAG Graph (`app/lineage/page.tsx`)

The signature visualization. Client component using `react-force-graph-2d`.

#### Requirements

- **Nodes** = conversations (colored by project, sized proportionally)
- **Edges** = compression hops (lineage edges)
- **Node labels** = conversation name (truncated to 20 chars)
- **Edge labels** = compression tag (on hover only)
- **Cross-project edges** = dashed, purple color
- **Click node** = navigate to `/lineage/[id]`
- **Project filter** = dropdown to filter by single project
- **Zoom/pan** = built into react-force-graph-2d

#### Data Flow

```
GET /api/lineage/graph?project={optional}
  -> { nodes: [{id, name, project}], edges: [{source, target, cross_project}] }
```

#### Color Scheme

Assign each project a distinct color from a palette. Cross-project edges use purple (`#a78bfa`).

#### Graph Configuration

```typescript
<ForceGraph2D
  graphData={data}
  nodeLabel="name"
  nodeColor={node => projectColorMap[node.project] || '#6b7280'}
  nodeRelSize={6}
  linkColor={link => link.cross_project ? '#a78bfa' : '#374151'}
  linkLineDash={link => link.cross_project ? [5, 5] : []}
  linkDirectionalArrowLength={4}
  onNodeClick={node => router.push(`/lineage/${node.id}`)}
  backgroundColor="#0a0a0a"
/>
```

---

### Phase 6: Conversation Trace (`app/lineage/[id]/page.tsx`)

Single conversation deep-dive. Vertical timeline showing the full lineage chain.

#### Layout

```
+-------------------------------------------+
|  < Back to Lineage                         |
|                                            |
|  Conversation: "Session 47 Attention..."   |
|  Project: Cheeky  |  Created: 2026-01-15  |
|  UUID: 1a2b3c4d-...                        |
+-------------------------------------------+
|                                            |
|  LINEAGE CHAIN                             |
|                                            |
|  [ROOT] Session 12 (Cheeky)               |
|     |                                      |
|     v  compression: CHEEKY_ATTENTION_V1    |
|        D001, D002 carried                  |
|                                            |
|  Session 23 (Cheeky)                       |
|     |                                      |
|     v  compression: CHEEKY_BRIDGE_V2       |
|        D001, D003 carried; T001 resolved   |
|                                            |
|  >> Session 47 (Cheeky) << YOU ARE HERE    |
|     |                                      |
|     v  compression: CROSS_PROJECT_MERGE    |
|        D001 carried (cross-project!)       |
|                                            |
|  Session 52 (The Nexus) [CROSS-PROJECT]    |
|                                            |
+-------------------------------------------+
```

#### Data Flow

```
GET /api/lineage/trace/{id}
  -> {conversation, ancestors, descendants, root, leaves, cross_project}
```

Each node in the chain enriched by resolving conversation UUIDs to names.

---

### Phase 7: Decision & Thread Registries

#### Decisions Page (`app/decisions/page.tsx`)

Cross-project decision view.

**Filters:**
- Project (dropdown, "All" default)
- Has conflicts (checkbox)
- Epistemic tier range (slider or dropdown: "High 0.8+", "Medium 0.3-0.7", "Low <0.3")
- Stale only (checkbox)

**Sort options:**
- Tier (desc) — default
- Date (newest first)
- Hops since validated (desc)

**Conflict pairs:** Clicking a `ConflictBadge` shows the conflicting decision side-by-side in a modal or expandable panel.

**Data:**
```
GET /api/decisions           -> All active decisions
GET /api/decisions/conflicts -> Decisions with conflicts_with != []
```

#### Threads Page (`app/threads/page.tsx`)

Cross-project thread view.

**Filters:**
- Project (dropdown)
- Status (open/blocked/all)
- Priority (high/medium/low)
- Stale only (checkbox)

**Sort options:**
- Priority (high first) — default
- Date (newest first)

**Data:**
```
GET /api/threads -> All active threads
```

---

### Phase 8: Semantic Search (`app/search/page.tsx`)

Client component (needs interactivity for input + results).

#### Layout

```
+-------------------------------------------+
|  SEARCH                                    |
|                                            |
|  [___________________________] [Search]    |
|                                            |
|  Scope: [Conversations] [Messages]         |
|         [Decisions] [Patterns]             |
|                                            |
|  Results:                                  |
|  +---------------------------------------+ |
|  | 0.89 | Cheeky | "Attention currency   | |
|  |      |        |  as fundamental..."    | |
|  +---------------------------------------+ |
|  | 0.82 | Nexus  | "The isomorphism      | |
|  |      |        |  between..."           | |
|  +---------------------------------------+ |
+-------------------------------------------+
```

#### Scope Mapping

| UI Scope | API `scope` | Backend Collection |
|----------|------------|-------------------|
| Conversations | `conversations` | `conversation_embeddings` |
| Messages | `messages` | `message_embeddings` |
| Decisions | `decisions` | `decision_registry` |
| Patterns | `patterns` | `patterns` |

The `scope` parameter maps to `collection_name` in `vector_search()`. The API server translates:

```python
SCOPE_MAP = {
    "conversations": "conversation_embeddings",
    "messages": "message_embeddings",
    "decisions": "decision_registry",
    "patterns": "patterns",
}
```

**Note:** Vector search on `decision_registry` and `patterns` requires those collections to have vector indexes (they do — set up in `ensure_forge_indexes()`).

#### Result Display

Each result shows:
- Similarity score (formatted to 2 decimal places)
- Project badge (colored)
- Content preview (truncated)
- Click → navigate to relevant detail page

---

## 6. Component Specifications

### `Sidebar.tsx`

- Fixed left sidebar, 240px width
- Dark background (`#1a1a2e`)
- Navigation links with icons (lucide-react)
- Active link highlighted
- "MISSION CONTROL" header text

### `StatsCard.tsx`

```typescript
interface StatsCardProps {
  label: string
  value: number
  icon?: React.ReactNode
}
```

- Dark card with subtle border
- Large number, small label below
- Optional icon

### `ProjectCard.tsx`

```typescript
interface ProjectCardProps {
  project: Project
  decisionCount?: number
  threadCount?: number
}
```

- Clickable card linking to `/projects/[name]`
- Shows: project name, conversation count, decision count, thread count
- Subtle hover effect

### `EpistemicTierBadge.tsx`

```typescript
interface EpistemicTierBadgeProps {
  tier: number | null
}
```

- Color: green (>=0.8), amber (0.3-0.7), red (<0.3), gray (null)
- Shows numeric tier value
- Tooltip with tier meaning

### `ConflictBadge.tsx`

```typescript
interface ConflictBadgeProps {
  conflictCount: number
  conflictUuids: string[]
}
```

- Red badge with count
- Clickable to show conflict details

### `StaleBadge.tsx`

```typescript
interface StaleBadgeProps {
  hopsSinceValidated: number
  lastValidated: string
}
```

- Amber/red badge showing hop count
- Appears when hops >= 3 (STALE_MAX_HOPS)

### `LineageGraph.tsx`

- Client component (`"use client"`)
- Uses `react-force-graph-2d`
- Project color mapping
- Node click navigation
- Zoom/pan controls
- Project filter dropdown

### `ConversationTrace.tsx`

- Vertical timeline component
- Each node: conversation name, project, date
- Edge annotations: compression tag, decisions carried/dropped, threads carried/resolved
- Cross-project hops highlighted in purple
- Current conversation highlighted

### `DecisionTable.tsx`

- Sortable, filterable table
- Columns: ID, Text, Tier, Status, Conflicts, Staleness
- Row click for detail expansion

### `ThreadTable.tsx`

- Sortable, filterable table
- Columns: ID, Title, Status, Priority, Blocked By, Staleness
- Status color coding

### `SearchBar.tsx`

- Client component
- Text input with debounced API call
- Scope toggle buttons
- Loading state

---

## 7. Visual Design Specification

### Theme: Dark Mode (Forge OS Terminal Aesthetic)

| Element | Color | Hex |
|---------|-------|-----|
| Background (primary) | Near black | `#0a0a0a` |
| Background (secondary) | Dark blue-black | `#1a1a2e` |
| Card background | Deep blue | `#16213e` |
| Card border | Medium blue | `#0f3460` |
| Accent | Deep blue | `#0f3460` |
| Text (primary) | Light gray | `#e0e0e0` |
| Text (secondary) | Muted blue-gray | `#8892b0` |
| Tier high (0.8+) | Green | `#4ade80` |
| Tier medium (0.3-0.7) | Amber | `#fbbf24` |
| Tier low (<0.3) | Red | `#ef4444` |
| Status active/open | Green | `#4ade80` |
| Status resolved | Gray | `#6b7280` |
| Status blocked/superseded | Red | `#ef4444` |
| Cross-project | Purple | `#a78bfa` |

### Typography

- **Headings:** System sans-serif (Inter/system-ui)
- **Body:** System sans-serif
- **IDs (D001, T001, UUIDs):** Monospace (`font-mono`)
- **Code/tags:** Monospace with background highlight

### Tailwind Config

```typescript
import type { Config } from 'tailwindcss'

const config: Config = {
  content: ['./app/**/*.{ts,tsx}', './components/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        forge: {
          bg: '#0a0a0a',
          surface: '#1a1a2e',
          card: '#16213e',
          border: '#0f3460',
          accent: '#0f3460',
        },
        tier: {
          high: '#4ade80',
          medium: '#fbbf24',
          low: '#ef4444',
        },
      },
    },
  },
  plugins: [],
}
export default config
```

---

## 8. Key Patterns & Constraints

### Server Components by Default

All pages are React Server Components. They fetch data at request time via the API.

```typescript
// app/page.tsx (Server Component - no "use client")
export default async function Dashboard() {
  const [stats, projects] = await Promise.all([
    api.getStats(),
    api.getProjects(),
  ])
  return <DashboardView stats={stats} projects={projects} />
}
```

### Client Components Only for Interactivity

- `LineageGraph.tsx` — zoom, pan, click, canvas rendering
- `SearchBar.tsx` — input state, debounce, API calls
- Filter/sort controls on Decision/Thread tables

### No State Duplication

Python API is the single source of truth. No client-side cache beyond Next.js built-in revalidation (`next: { revalidate: 30 }`). No Redux, no Zustand, no client-side state management library.

### Existing Function Reuse

Every API endpoint wraps an existing `vectordb/` function. No new MongoDB queries except:
1. `count_documents({})` for the stats endpoint
2. The `conflicts_with: {$ne: []}` query for the conflicts endpoint

### Error Handling

```typescript
// lib/api.ts
async function fetchAPI<T>(path: string): Promise<T> {
  try {
    const res = await fetch(url)
    if (!res.ok) {
      throw new Error(`API error: ${res.status}`)
    }
    return res.json()
  } catch (error) {
    console.error(`Failed to fetch ${path}:`, error)
    throw error
  }
}
```

Server components use try/catch with fallback UI. Client components show loading/error states.

### URL Encoding

Project names may contain spaces and special characters (e.g., "The Cartographer's Dilemma"). All path params must be `encodeURIComponent()`-ed in the frontend and decoded in FastAPI.

---

## 9. Verification Checklist

### Infrastructure

- [ ] MongoDB running: `scripts/start_mongodb.sh`
- [ ] Python API running: `python scripts/api_server.py` on port 8000
- [ ] Next.js dev running: `cd web && npm run dev` on port 3000

### API Verification

```bash
# Stats
curl http://localhost:8000/api/stats
# Expected: {"conversations": 229, "projects": 15, "decisions": 138, ...}

# Projects
curl http://localhost:8000/api/projects
# Expected: 15 projects sorted by conversation count

# Lineage graph
curl http://localhost:8000/api/lineage/graph
# Expected: {nodes: [...], edges: [...]}

# Search
curl "http://localhost:8000/api/search?q=attention&scope=conversations&limit=5"
# Expected: [{text: "...", score: 0.85, ...}]
```

### Frontend Verification

1. Open `http://localhost:3000` — should show project overview with real data
2. Verify 6 stats cards show correct counts
3. Click a project card — navigates to `/projects/[name]` with tabs
4. Check Decisions tab shows epistemic tier badges
5. Check Threads tab shows priority/status badges
6. Navigate to `/lineage` — interactive force-directed graph renders
7. Click a node in the graph — navigates to `/lineage/[id]` trace view
8. Verify trace shows ancestor/descendant chain
9. Navigate to `/decisions` — cross-project decision list with filters
10. Navigate to `/threads` — cross-project thread list with filters
11. Navigate to `/search` — type "attention" — results appear with scores
12. Verify cross-project edges in lineage graph are purple/dashed

---

## 10. Dependency Summary

### Python (add to `requirements.txt`)

```
fastapi>=0.104.0
uvicorn>=0.24.0
```

### Node.js (`web/package.json`)

```json
{
  "dependencies": {
    "next": "^15",
    "react": "^19",
    "react-dom": "^19",
    "react-force-graph-2d": "^1.25",
    "d3": "^7",
    "lucide-react": "^0.400"
  },
  "devDependencies": {
    "@types/node": "^22",
    "@types/react": "^19",
    "typescript": "^5",
    "tailwindcss": "^4",
    "postcss": "^8"
  }
}
```

---

## 11. File Size Estimates

| File | Est. Lines | Notes |
|------|-----------|-------|
| `scripts/api_server.py` | ~250 | FastAPI thin wrappers |
| `web/app/layout.tsx` | ~80 | Root layout + sidebar |
| `web/app/page.tsx` | ~120 | Dashboard with stats + projects + alerts |
| `web/app/projects/[name]/page.tsx` | ~250 | Tabbed project detail |
| `web/app/lineage/page.tsx` | ~100 | Graph page (thin wrapper) |
| `web/app/lineage/[id]/page.tsx` | ~150 | Conversation trace |
| `web/app/decisions/page.tsx` | ~120 | Decision registry |
| `web/app/threads/page.tsx` | ~100 | Thread registry |
| `web/app/search/page.tsx` | ~120 | Search interface |
| `web/app/globals.css` | ~40 | Theme variables |
| `web/components/Sidebar.tsx` | ~60 | Nav sidebar |
| `web/components/ProjectCard.tsx` | ~40 | Project summary card |
| `web/components/DecisionTable.tsx` | ~80 | Decision list |
| `web/components/ThreadTable.tsx` | ~70 | Thread list |
| `web/components/LineageGraph.tsx` | ~120 | Force-directed graph |
| `web/components/ConversationTrace.tsx` | ~100 | Timeline chain view |
| `web/components/ConflictBadge.tsx` | ~25 | Conflict indicator |
| `web/components/StaleBadge.tsx` | ~25 | Stale warning |
| `web/components/EpistemicTierBadge.tsx` | ~30 | Tier color badge |
| `web/components/SearchBar.tsx` | ~60 | Search input |
| `web/components/StatsCard.tsx` | ~25 | Metric card |
| `web/lib/api.ts` | ~80 | API client |
| `web/lib/types.ts` | ~180 | TypeScript interfaces |
| **Total** | **~2,225** | |

---

## 12. Phase Execution Order & Dependencies

```
Phase 1: Python API Server
  |
  +-> Phase 2: Next.js Scaffold (parallel: can start while API builds)
  |     |
  |     +-> Phase 3: Dashboard (needs API + scaffold)
  |     |
  |     +-> Phase 4: Project Detail (needs API + scaffold)
  |     |
  |     +-> Phase 5: Lineage Graph (needs API + scaffold)
  |     |
  |     +-> Phase 6: Conversation Trace (needs API + scaffold)
  |     |
  |     +-> Phase 7: Decision & Thread Registries (needs API + scaffold)
  |     |
  |     +-> Phase 8: Search (needs API + scaffold)
  |
  (Phases 3-8 can be developed in parallel after Phase 1+2)
```

**Critical path:** Phase 1 (API) -> Phase 2 (Scaffold) -> Phase 3 (Dashboard) is the minimum viable path to a working screen.

**Parallelizable after Phase 2:** Phases 3-8 are independent of each other and can be built in any order or concurrently.
