# Forge OS — Persistent Semantic Memory for LLMs

Forge OS gives LLMs something they don't have: **memory that persists across conversations, spans projects, and gets smarter over time.**

Every Claude conversation starts cold. Past decisions evaporate. Open questions vanish. Cross-project connections are invisible. Forge OS fixes this by building a living knowledge graph from your Claude.ai projects and exposing it through an attention-weighted recall engine that any LLM can query.

## What This Does

Forge OS ingests conversations from Claude.ai projects and transforms them into a structured, searchable knowledge graph stored in MongoDB Atlas with VoyageAI embeddings. It tracks:

- **138+ decisions** with epistemic confidence tiers and conflict detection
- **22+ open threads** (questions, blockers, unresolved work)
- **Lineage edges** tracing how decisions flow across compression hops
- **Entanglement clusters** revealing cross-project semantic resonances
- **Priming blocks** compiled from expedition findings
- **Patterns** learned from successful approaches
- **Expedition flags** bookmarking observations for future compilation

Then it exposes all of this to LLMs through three interfaces:

| Interface | Transport | For |
|-----------|-----------|-----|
| **MCP Server** | stdio | Claude Code (native MCP support) |
| **REST API** | HTTP | Any LLM via function calling |
| **Tool Schemas** | JSON export | OpenAI, Anthropic, Gemini tool formats |

## How It's Different from Plain Claude

| | Plain Claude | Claude + Forge OS |
|---|---|---|
| **Memory** | Starts cold every conversation | Recalls past decisions, threads, patterns |
| **Cross-project** | No awareness of other projects | Detects entanglement clusters across 8+ projects |
| **Decisions** | Lost at context boundary | Persisted, conflict-checked, epistemically tiered |
| **Open questions** | Forgotten after compression | Tracked as threads with staleness alerts |
| **Patterns** | Re-discovered each session | Stored and merged with confidence scores |
| **Write-back** | LLM output is ephemeral | LLM registers decisions, threads, flags into the graph |
| **Conflict detection** | None | Two-signal detection (embedding similarity + entity divergence) |
| **Staleness** | No concept of it | Hop counting + time-based decay alerts |

## The Attention Engine

Plain vector search tells you "how semantically close." The attention engine tells you "how important." Each result is scored by:

```
attention = similarity × 0.45      # semantic relevance
          + epistemic_tier × 0.20  # confidence level
          + freshness × 0.15       # exponential decay (30-day half-life)
          + conflict_bonus × 0.10  # demands attention if conflicts exist
          + category_boost × 0.10  # decisions > threads > priming > patterns > messages
```

This means a validated decision from yesterday outranks a vaguely similar message from three months ago, even if the raw cosine similarity is identical.

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                    LLM Layer                         │
│  Claude Code (MCP) ─── GPT-4 (HTTP) ─── Any LLM    │
└──────────┬──────────────────┬────────────────────────┘
           │ stdio            │ HTTP POST
           ▼                  ▼
┌──────────────────┐  ┌─────────────────────┐
│ scripts/          │  │ scripts/             │
│  mcp_server.py   │  │  api_server.py       │
│  (14 MCP tools)  │  │  (14 /api/forge/*    │
│                  │  │   + 40 existing)     │
└────────┬─────────┘  └──────────┬───────────┘
         │                       │
         ▼                       ▼
┌──────────────────────────────────────────┐
│        vectordb/attention.py              │
│  Attention-weighted cross-collection      │
│  recall engine (LLM-agnostic core)        │
└──────────────────┬───────────────────────┘
                   │
                   ▼
┌──────────────────────────────────────────┐
│         vectordb/ (28 modules)            │
│  decisions · threads · lineage · patterns │
│  priming · entanglement · scratchpad      │
│  conflicts · flags · archive · embeddings │
└──────────────────────────────────────────┘
                   │
                   ▼
            MongoDB Atlas + VoyageAI
```

## 14 LLM Tools

### Read Tools
| Tool | Purpose |
|------|---------|
| `forge_recall` | Attention-weighted search across all 6 collections |
| `forge_project_context` | Full project state (decisions, threads, flags, stale, conflicts) |
| `forge_entanglement` | Cross-project resonance clusters and bridges |
| `forge_trace` | Lineage traversal through compression hops |
| `forge_alerts` | System-wide staleness, conflicts, pending flags |
| `forge_search` | Scoped vector search on a single collection |
| `forge_stats` | System overview with collection counts |
| `forge_projects` | All projects with decision/thread/flag counts |
| `forge_session` | Current session scratchpad state |

### Write Tools
| Tool | Purpose |
|------|---------|
| `forge_decide` | Register a decision with auto conflict detection |
| `forge_thread` | Track an open question or resolve a thread |
| `forge_flag` | Bookmark an observation for expedition compilation |
| `forge_pattern` | Store a learned pattern (auto-merges similar) |
| `forge_remember` | Session scratchpad (TTL key-value store) |

## Quick Start

### Prerequisites

- Python 3.10+
- MongoDB Atlas cluster with vector search indexes
- VoyageAI API key (`VOYAGE_API_KEY`)
- Firefox with a profile logged into claude.ai (for sync)

### 1. Install Dependencies

```bash
pip install pymongo voyageai fastapi uvicorn mcp
```

### 2. Set Environment Variables

```bash
export MONGODB_URI="mongodb+srv://..."
export VOYAGE_API_KEY="pa-..."
```

### 3. Connect Claude Code (MCP)

```bash
claude mcp add forge-os -- python scripts/mcp_server.py
```

Then in any Claude Code session:
```
> forge_recall("authentication patterns")
> forge_stats()
> forge_decide("Use JWT with refresh tokens", "My Project", "D042", tier=0.8)
```

### 4. Start the HTTP API

```bash
python scripts/api_server.py
# Runs on http://localhost:8000
```

```bash
curl -X POST http://localhost:8000/api/forge/recall \
  -H 'Content-Type: application/json' \
  -d '{"query": "authentication patterns", "budget": 2000}'
```

### 5. Export Tool Schemas (for GPT-4, Gemini, etc.)

```bash
python scripts/export_tool_schemas.py
# Generates:
#   config/forge_tools_openai.json
#   config/forge_tools_anthropic.json
#   config/forge_system_prompt.txt
```

## Project Structure

```
├── vectordb/                  # Core library (28 modules, ~8,500 lines)
│   ├── attention.py           # Attention-weighted recall engine
│   ├── decision_registry.py   # Decision CRUD + conflict detection
│   ├── thread_registry.py     # Thread tracking + resolution
│   ├── entanglement.py        # Cross-project resonance discovery
│   ├── lineage.py             # Compression-hop lineage graph
│   ├── priming_registry.py    # Expedition priming blocks
│   ├── patterns.py            # Learned pattern store + merge
│   ├── expedition_flags.py    # Observation bookmarks
│   ├── conflicts.py           # Two-signal conflict detection
│   ├── embeddings.py          # VoyageAI embedding (voyage-3, 1024-dim)
│   ├── context.py             # Legacy context assembly
│   ├── scratchpad.py          # TTL key-value session state
│   ├── conversation_registry.py # UUIDv8 identity registry
│   ├── vector_store.py        # Generic vector store/search
│   ├── uuidv8.py              # Deterministic UUIDv8 identity system
│   ├── sync_engine.py         # Claude.ai project sync
│   ├── claude_api.py          # Claude.ai session client
│   └── ...
├── scripts/
│   ├── mcp_server.py          # MCP server (14 tools, stdio)
│   ├── api_server.py          # FastAPI REST server
│   ├── export_tool_schemas.py # OpenAI/Anthropic schema generator
│   ├── run_sync.py            # Claude.ai sync runner
│   └── ...
├── web/                       # Next.js dashboard (Mission Control)
│   └── app/
│       ├── projects/          # Project explorer
│       ├── decisions/         # Decision registry viewer
│       ├── threads/           # Thread tracker
│       ├── lineage/           # Lineage graph visualizer
│       ├── entanglement/      # Entanglement cluster viewer
│       └── search/            # Semantic search interface
├── config/
│   ├── sync_manifest.yaml     # Declarative sync configuration
│   ├── forge_tools_openai.json
│   ├── forge_tools_anthropic.json
│   └── forge_system_prompt.txt
└── examples/
    └── fetch_conversations.py
```

## How the Sync Pipeline Works

1. **Fetch** — Pull conversations from Claude.ai via browser session cookies
2. **Parse** — Extract decisions (D001...), threads (T001...), compression archives
3. **Identity** — Assign deterministic UUIDv8 identifiers to everything
4. **Embed** — Generate VoyageAI embeddings (voyage-3, 1024 dimensions)
5. **Detect** — Run conflict detection and entanglement scans
6. **Store** — Upsert into MongoDB Atlas with vector search indexes
7. **Serve** — Expose via MCP, HTTP, and exported tool schemas

## Benefits

**For individual developers:**
- Never re-explain context to Claude. Past decisions are recalled automatically.
- Track open questions across sessions. Nothing falls through the cracks.
- Detect when new decisions conflict with established ones before committing.

**For multi-project work:**
- Discover cross-project patterns you didn't know existed (entanglement).
- Carry validated decisions across project boundaries via lineage.
- Use expedition flags to bookmark insights during exploration for later synthesis.

**For teams:**
- Shared decision registry with epistemic tiers (how confident is this decision?).
- Staleness alerts surface decisions that haven't been validated recently.
- Audit trail via event logging tracks every read and write.

**For LLM workflows:**
- MCP integration means zero-config for Claude Code users.
- HTTP API + exported schemas work with any LLM that supports function calling.
- Session scratchpad enables multi-turn workflows without losing intermediate state.

## Disclaimer

This project uses an unofficial API for accessing Claude.ai conversations. It is not endorsed, supported, or maintained by Anthropic. Use at your own discretion. The sync pipeline requires browser session cookies from a logged-in Claude.ai account.
