# Forge OS Implementation Plan

**Date:** 2026-02-08
**Status:** Planning
**References:** forge-os-architecture.md, context-rot-assessment.md, updated-context-compression-assessment.md, local-llm-migration.md, forge-os/*.md specs

---

## Situation

Forge OS exists as two things simultaneously:

1. **A set of Claude Projects** (Track A) -- The Arbiter, The Evaluator, Mission Control, The Guardian, plus existing projects (Transmutation Forge, Reality Compiler, Cartographer's Codex, Applied Alchemy, CTH-2026, The Nexus). These are personas defined by custom instructions and knowledge files within Claude.ai.

2. **This codebase** (the bridge) -- `unofficial-claude-api` with `claude_api/` (conversation fetcher) and `vectordb/` (Layer 0-1: vector store, embeddings, patterns, context, archive, events, classifier, chunker, pipeline, UUIDv8, scratchpad). Currently Python, MongoDB, VoyageAI.

The eventual target is **Track B** -- a fully local Forge OS running on a Mac Studio (or GCP staging first), with multi-model routing, quality gates, orchestration, and safety constraints all running as code rather than Claude Project custom instructions. The tech stack for Track B is specified as Kotlin 2.0 + PostgreSQL + pgvector + MongoDB + Atlas Vector Search + VoyageAI + Redis (see `forge-os/FORGE_OS_LOCAL_ARCHITECTURE_KOTLIN.md`). MongoDB and VoyageAI carry through from this codebase to Track B — no data migration needed for document/vector workloads.

**This codebase is the stepping stone between Track A and Track B.** It starts by making Track A work better (automating coordination between Claude Projects), and over time absorbs more responsibility until Track B becomes viable.

---

## What Exists (Layer 0-1)

### Layer 0: Data

| Component | File | Status |
|-----------|------|--------|
| Conversation fetcher | `claude_api/client.py`, `claude_api/session.py` | Implemented |
| Conversation storage | `data/conversations/*.json` (~100 synced) | Implemented |
| Project registry | `data/projects.json` | Implemented |
| Artifact extraction | `data/artifacts/` | Implemented |
| MongoDB connection | `vectordb/db.py`, `vectordb/config.py` | Implemented |
| Docker Compose (MongoDB) | `docker/docker-compose.yml` | Implemented |

### Layer 1: Memory

| Component | File | Status |
|-----------|------|--------|
| Vector store + search | `vectordb/vector_store.py` | Implemented |
| Embeddings (VoyageAI) | `vectordb/embeddings.py` | Implemented |
| Content classifier | `vectordb/classifier.py` (rule-based regex) | Implemented |
| Document chunker | `vectordb/chunker.py` | Implemented |
| Pattern store/match | `vectordb/patterns.py` | Implemented |
| Context management | `vectordb/context.py` | Implemented |
| Scratchpad (TTL key-value) | `vectordb/scratchpad.py` | Implemented |
| Archive store | `vectordb/archive.py` | Implemented |
| Event log | `vectordb/events.py` | Implemented |
| Sync pipeline | `vectordb/pipeline.py` | Implemented |
| Migration utilities | `vectordb/migration.py` | Implemented |
| UUIDv8 identity system | `vectordb/uuidv8.py` | Implemented |
| Search CLI | `scripts/search.py` | Implemented |

---

## What's Missing

### Layer 1.5: Sync (the bridge between Claude and the vectordb)

This is the most critical gap. Claude cannot query MongoDB from inside its context window. The sync layer bridges that divide. Three scripts are needed (identified in `context-rot-assessment.md` and `forge-os-architecture.md`):

| Script | Purpose | Inputs | Outputs |
|--------|---------|--------|---------|
| `prepare_compression.py` | Runs BEFORE user compresses in Claude. Queries vectordb for active threads, stale decisions, cross-project conflicts, and relevant context from other projects. | Project name, optional topic keywords | Structured text block the user pastes into Claude alongside `compress --lossless` |
| `sync_compression.py` | Runs AFTER user compresses in Claude. Parses the archive output and syncs new/updated decisions, thread status changes, and lineage metadata back to the vectordb. | Archive text (pasted or piped in) | Updated thread registry, decision registry, lineage edges in MongoDB |
| `prepare_continuation.py` | Runs BEFORE starting a new conversation from an archive. Pulls current registry state by compression tag so the user gets up-to-date context (not stale archive state). | Compression tag or conversation ID | Structured context block with current thread/decision state, flagged conflicts |

Flow:
```
User wants to compress
  -> runs prepare_compression.py (assembles current state from vectordb)
  -> pastes output into Claude alongside compress --lossless
  -> Claude compresses with accurate state
  -> user copies archive output
  -> runs sync_compression.py (parses archive, updates vectordb)

User wants to continue from archive
  -> runs prepare_continuation.py (pulls fresh state, flags stale items)
  -> pastes output + archive into new Claude conversation
  -> Claude resumes with accurate, conflict-checked state
```

### Layer 2: Graph (conversation lineage DAG)

The architecture doc (`forge-os-architecture.md`) identifies this as the structural heart of Forge OS -- the thing that makes it more than "smart version control." Currently, conversations are flat JSON files with no relationship tracking.

| Component | Purpose | Dependencies |
|-----------|---------|-------------|
| **Thread registry** | Global registry of all threads (T001, T002...) across all projects with current status, owner project, and cross-references. Uses UUIDv8 deterministic IDs. | `vectordb/uuidv8.py`, MongoDB |
| **Decision registry** | Global registry of all decisions (D001, D002...) with epistemic tiers, provenance, `conflicts_with` edges, and `dependents` chains. | `vectordb/uuidv8.py`, MongoDB |
| **Lineage graph** | DAG of conversation-to-conversation inheritance. Each edge represents a compression -> continuation hop. Built retroactively from compression tags and archive references. | UUIDv8 `compositePair()` for edge IDs |
| **Conflict detector** | Semantic similarity search across active decisions. When similarity > 0.85 but conclusions differ, register a `conflicts_with` edge. | `vectordb/vector_store.py`, `vectordb/embeddings.py` |
| **Decay tracker** | Flag decisions and threads that haven't been validated in N compression hops. Track `last_validated` timestamps and hop counts. | Thread/decision registries |

**Decay & validation policy:**

A decision is **validated** when it appears in a `FORGE_OS_MACHINE_BLOCK` with its status unchanged. Validation is implicit — no explicit "I reaffirm D007" needed. When `sync_compression.py` processes an archive:
- If a decision appears in the machine block with the same status and tier, update `last_validated` to the archive's timestamp and reset its hop counter.
- If a decision appears with a changed status or tier, treat it as an update (upsert), not a validation.
- If a decision does NOT appear in the machine block, increment its hop counter by 1.

**Stale thresholds:**
- Flag as **stale** after **3 compression hops** without validation, OR **30 days** since `last_validated`, whichever comes first.
- Stale decisions are surfaced with a warning in `prepare_continuation.py` output but are NOT auto-removed.
- Stale decisions carry a visual flag (e.g., `[STALE: 5 hops, 42 days]`) so Claude can decide whether to reaffirm, revise, or drop them.

Conflict resolution policy (from `forge-os-architecture.md` and `updated-context-compression-assessment.md`):

| Scenario | Auto-resolve? | Action |
|----------|:---:|--------|
| Same project, tier gap > 0.4 | Yes | Higher tier wins, log resolution |
| Same project, tier gap <= 0.4 | No | Surface both, user chooses |
| Cross-project contradiction | Never | Surface as conflict, block carry-forward |
| Dependency chain broken by revision | N/A | Flag all dependents for revalidation |

### Layer 3: Attention (cross-project context assembly)

This is where the system starts to feel intelligent. Instead of the user manually deciding what context to pull from which project, the system predicts and assembles relevant context.

| Component | Purpose |
|-----------|---------|
| **context_load()** | Given a project and topic, assemble relevant decisions, threads, and patterns from across ALL projects (not just the current one). Weight by recency, validation frequency, and project relevance. |
| **Persona-aware retrieval** | Tag conversations and documents by persona/project. Scope retrieval to the right knowledge domains while still surfacing cross-project connections. |
| **Stale context detection** | Before injecting inherited context into a new conversation, check if any of the carried-forward decisions have been superseded, conflicted, or decayed. Flag them. |

### What's NOT Needed in Code (yet)

These live as Claude Project custom instructions in Track A. They move into code only when Track B (fully local) is being built:

| Component | Lives In | Why Not Code Yet |
|-----------|----------|-----------------|
| Arbiter routing logic | Claude Project custom instructions | Claude-as-persona does the reasoning about which model to use |
| Evaluator scoring engine | Claude Project custom instructions | Claude-as-persona evaluates quality and assigns tiers |
| Mission Control task decomposition | Claude Project custom instructions | Claude-as-persona plans and tracks |
| Guardian veto/escalation | Claude Project custom instructions | Claude-as-persona enforces constraints |
| Persona system prompts | Claude Project knowledge files | Already defined in the spec docs |

---

## Implementation Order

### Step 1: Create Claude Projects (Track A, no code)

Set up the 4 new Claude Projects using the specs in `.docs/forge-os/`:

| Project | Spec File | Key Knowledge Files to Create |
|---------|-----------|------------------------------|
| The Arbiter | `FORGE_OS_THE_ARBITER_PROJECT_SPEC.md` | Model registry (YAML), routing policies |
| The Evaluator | `FORGE_OS_THE_EVALUATOR_PROJECT_SPEC.md` | Evaluation criteria, epistemic tiers, gate configs, evaluation log |
| Mission Control | `FORGE_OS_MISSION_CONTROL_PROJECT_SPEC.md` | Active missions, task registry, workflow templates, milestone history |
| The Guardian | `FORGE_OS_THE_GUARDIAN_PROJECT_SPEC.md` | Active constraints, violation log, escalation log, blind spot archive, principles |

Each project gets its custom instructions block (already written in the spec) and the knowledge files listed in its implementation checklist.

**1b: Update Transmutation Forge compression skill**

The `compress --lossless` skill must be updated to emit a `FORGE_OS_MACHINE_BLOCK` (versioned YAML) at the end of each archive. This is a prerequisite for Step 2 — the sync scripts parse this block instead of regex-matching the human-readable narrative. The machine block contains structured decisions, threads, artifacts, lineage, and a compression tag. See Open Questions #1 (resolved) for the full spec.

### Step 2: Sync Layer (Layer 1.5)

Build the three sync scripts that bridge Claude's sandbox to the vectordb. This is the highest-value code work because it directly reduces the manual shuttle burden.

**2a: `prepare_compression.py`**
- Query MongoDB for all active threads in the target project
- Query for decisions with `last_validated` older than N days
- Run conflict detection across projects (vector similarity search)
- Query for cross-project context relevant to the current topic
- Format as structured text block suitable for pasting into Claude

**2b: `sync_compression.py`**
- Parse `FORGE_OS_MACHINE_BLOCK` from archive text (strict YAML, versioned schema)
- If machine block missing or malformed: abort with error, notify user to re-run compression with updated skill
- Extract decisions with tiers, threads with status, artifacts with versions
- Generate UUIDv8 IDs for each entity (deterministic from content)
- Upsert into MongoDB registries (thread_registry, decision_registry collections)
- Build lineage edges using `compositePair()`
- Run conflict detection against existing decisions
- Log sync event to events collection

**2c: `prepare_continuation.py`**
- Look up compression tag in lineage graph
- Pull current state of all threads and decisions referenced in the archive
- Compare archive state vs. registry state, flag discrepancies
- Surface any conflicts detected since the archive was created
- Format as context block for pasting into new conversation

### Step 3: Registries (Layer 2 foundation)

Build the MongoDB collections and Python modules for thread and decision tracking.

**3a: Thread registry**
- MongoDB collection: `thread_registry`
- Schema: `{uuid, title, status, project, first_seen_conversation, last_updated_conversation, priority, blocked_by, resolution, epistemic_tier}`
- UUIDv8 ID: `UUIDv8(project_uuid, thread_title + first_seen_conversation_id)`
- Operations: `upsert_thread()`, `get_active_threads(project)`, `resolve_thread()`, `get_stale_threads(age_days)`

**3b: Decision registry**
- MongoDB collection: `decision_registry`
- Schema: `{uuid, text, text_hash, project, epistemic_tier, originated_conversation, last_validated, hops_since_validated, conflicts_with[], dependents[], superseded_by, status}`
- UUIDv8 ID: `UUIDv8(project_uuid, decision_text_hash + originated_conversation_id)`
- Operations: `upsert_decision()`, `get_active_decisions(project)`, `find_conflicts(decision)`, `cascade_revalidation(decision_id)`, `get_stale_decisions(max_hops=3, max_days=30)`

**3c: Lineage graph**
- MongoDB collection: `lineage_edges`
- Schema: `{edge_uuid, source_conversation, target_conversation, compression_tag, edge_type, created_at}`
- UUIDv8 ID: `compositePair(source_conversation_id, target_conversation_id)`
- Operations: `add_edge()`, `get_ancestors(conversation_id)`, `get_descendants(conversation_id)`, `get_lineage_chain(compression_tag)`

### Step 4: Conflict Detection

Build the semantic contradiction detector on top of the existing vector store. Uses two complementary signals to catch both near-duplicate contradictions and topically related disagreements.

**Signal 1: Embedding similarity (catches near-duplicates)**
- For each new/updated decision, embed it with VoyageAI and search existing active decisions via Atlas Vector Search
- If cosine similarity > 0.85 but conclusions differ (heuristic: different action verbs, negation patterns, or tier assignments), flag as conflict
- This catches: "Use JWT for auth" vs. "Use session cookies for auth"

**Signal 2: Entity/topic overlap (catches differently-expressed contradictions)**
- Extract entities from each decision via regex: decision IDs (D001), project names, and key terms (technology names, architectural patterns, domain nouns)
- If two decisions share the same topic entities but have different tier assignments or opposing conclusions, flag as potential conflict
- This catches: a Tier 0.9 decision in Project A that contradicts a Tier 0.4 decision on the same topic in Project B, even if phrased completely differently
- Entity extraction is lightweight regex, not NLP — decision IDs, project names, and key terms cover most cases

**Conflict registration:**
- Register `conflicts_with` edges on both decision documents
- Apply auto-resolution policy for same-project, high tier-gap conflicts
- Surface unresolvable conflicts in `prepare_continuation.py` output
- Tag each conflict with its detection signal (`embedding_similarity` or `entity_overlap`) for debugging

### Step 5: Pipeline Integration

Wire the sync layer into the existing `pipeline.py` conversation sync flow.

- During batch sync (`sync_claude.sh` / `pipeline.py`), scan each conversation for:
  - Compression tags (to build lineage edges retroactively)
  - Decision patterns (D001, D002... with tier assignments)
  - Thread patterns (T001, T002... with status)
  - Archive blocks (to extract and register entities)
- Populate thread_registry, decision_registry, and lineage_edges from historical data
- This gives the graph an initial state built from the ~100 existing conversations

### Step 6: Cross-Project Context Assembly (Layer 3)

Build `context_load()` and persona-aware retrieval.

- Given project + topic, query decisions and threads across all projects
- Weight results: current project (1.0x) > related projects (0.7x) > unrelated (0.3x)
- Weight by recency: `score *= decay_factor(days_since_last_validated)`
- Weight by tier: `score *= epistemic_tier`
- Return assembled context block with provenance annotations
- Flag stale items (not validated in N hops or N days)

---

## What This Enables

After Steps 1-6, the workflow becomes:

```
1. User decides to work on a topic in project X
2. Runs: prepare_continuation.py --project X --topic "authentication design"
3. Gets: assembled context with relevant decisions from ALL projects,
   flagged conflicts, stale items marked, cross-project connections surfaced
4. Pastes into Claude Project X
5. Works normally
6. When done, runs: compress --lossless (in Claude)
7. Copies archive
8. Runs: sync_compression.py < archive.txt
9. Vectordb updated, conflicts detected, lineage edge created
```

The human is still in the loop, but the system handles:
- What context to assemble (was manual)
- What's stale or conflicting (was invisible)
- Registry updates (was lost)
- Cross-project awareness (was manual shuttling via The Nexus)

**Known friction point: manual invocation.** The user has to remember to run the scripts at the right time. Forgetting `sync_compression.py` after a session means that session's decisions, threads, and lineage never reach the vectordb — silent data loss by omission.

**Stepping stone mitigation (this phase):**
- Document the ritual as a checklist in a `scripts/README.md` or similar
- Build a thin wrapper script (`scripts/forge_session.sh`) that walks the user through the full cycle: prepare -> work -> compress -> sync. After sync, it confirms what was written ("3 decisions upserted, 1 conflict detected, lineage edge created")
- The wrapper prompts "Did you compress? Paste archive:" if invoked without piped input

**Track B eliminates this entirely** — see Track B migration section below.

---

## Track B Migration (future, not this phase)

When the stepping stone is proven, Track B absorbs the Claude Project logic into code:

| Migration | What Moves |
|-----------|-----------|
| Arbiter -> code | Model registry + scoring engine + routing policies + failover logic become a Kotlin/Python service. Claude stops being the only model. |
| Evaluator -> code | Quality scoring + gate evaluation + tier assignment become automated. Claude outputs are evaluated programmatically. |
| Mission Control -> code | Task decomposition + dependency graphs + progress tracking become a persistent system. Tasks don't vanish with context windows. |
| Guardian -> code | Constraint checking + veto logic + resource monitoring become always-on enforcement. |
| Language migration | Python -> Kotlin 2.0. MongoDB + VoyageAI stay as-is (same collections, same embedding model). PostgreSQL + Redis are added for relational data and caching. |
| Deployment | GCP staging (per `FORGE_OS_GCP_DEPLOYMENT_GUIDE.md`) -> Mac Studio local |

**What stays the same across the migration:** MongoDB collections (messages, archives, thread_registry, decision_registry, lineage_edges, knowledge_chunks, patterns, events, scratchpad), Atlas Vector Search indexes, and VoyageAI embeddings all carry through unchanged. The Kotlin code connects to the same MongoDB instance with the same data.

**What's added in Track B:** PostgreSQL for relational data (model registry, routing logs, cost tracking, personas), Redis for caching/queuing, and the Kotlin application layer.

Track B also introduces capabilities that Track A cannot provide:
- Local LLM routing (Ollama, no API dependency)
- Autonomous compression triggers (no human command needed)
- Autonomous sync (Claude API polling detects new conversations and archives, runs sync automatically — eliminates the manual invocation friction point)
- Autonomous merge and conflict resolution (no human shuttle)
- Predictive context assembly (system suggests what to load)
- Goal-directed graph traversal (system suggests what to work on next)

These correspond to Layers 3-4 in the architecture doc and represent the transition from "tool" to "agent."

---

## File Organization

All new code follows the existing pattern and the project rules:

```
vectordb/
  (existing files stay)
  thread_registry.py      # Step 3a
  decision_registry.py    # Step 3b
  lineage.py              # Step 3c
  conflicts.py            # Step 4
  context_assembler.py    # Step 6

scripts/
  prepare_compression.py  # Step 2a
  sync_compression.py     # Step 2b
  prepare_continuation.py # Step 2c
```

No new directories. No files in root. Tests go in `tests/`.

---

## Dependencies on Existing Work

| This Plan Needs | Status | Notes |
|----------------|--------|-------|
| `vectordb/uuidv8.py` | Implemented | Deterministic IDs, `compositePair()` |
| `vectordb/vector_store.py` | Implemented | Similarity search for conflict detection |
| `vectordb/embeddings.py` | Implemented | VoyageAI embedding generation |
| `vectordb/pipeline.py` | Implemented | Conversation sync pipeline (needs extension in Step 5) |
| `vectordb/db.py` | Implemented | MongoDB connection management |
| `vectordb/config.py` | Implemented | Configuration (MongoDB URI, etc.) |
| `vectordb/classifier.py` | Implemented | Content type classification (may need extension for archive detection) |
| `data/conversations/*.json` | ~100 files | Historical data for retroactive graph building in Step 5 |
| `data/projects.json` | Implemented | Project registry for persona-aware retrieval |

---

## Open Questions

1. ~~**Archive format parsing**~~ **Resolved.** The compression skill (`compress --lossless` in Transmutation Forge) will be updated to emit a strict, versioned machine-readable block at the end of each archive, in addition to the existing human-readable narrative. The sync scripts parse the machine block only — the human-readable parts can vary freely without breaking the pipeline.

   **Machine block spec:**
   ```yaml
   <!-- FORGE_OS_MACHINE_BLOCK v1 -->
   schema_version: 1
   compression_tag: "TF-2026-02-08-001"
   decisions:
     - id: D001
       text: "Decision text"
       tier: 0.85
       status: active
   threads:
     - id: T001
       title: "Thread title"
       status: resolved
   artifacts:
     - id: A001
       type: code
       version: 2
   lineage:
     parent_conversation: "conv_abc123"
   <!-- /FORGE_OS_MACHINE_BLOCK -->
   ```

   **Failure mode:** If the machine block is missing or malformed, `sync_compression.py` aborts and notifies the user. Never silent data loss. The user re-runs compression with the updated skill prompt.

   **Prerequisite:** Update the Transmutation Forge compression skill prompt to emit this block. This is Track A work (Step 1) and must happen before Step 2 can be built.

2. **Embedding granularity for conflict detection** -- Partially addressed by the two-signal approach in Step 4. Signal 1 (embedding similarity) uses VoyageAI on full decision text and catches near-duplicates. Signal 2 (entity/topic overlap) catches differently-expressed contradictions without relying on embeddings at all. Remaining question: should Signal 1 embed the full decision text or just the conclusion/action? Start with full text; if false positive rate is too high, narrow to conclusion only.

3. ~~**MongoDB schema for registries**~~ **Resolved.** MongoDB is the document/vector store in both the stepping stone AND Track B. New registries (thread_registry, decision_registry, lineage_edges) become MongoDB collections with Atlas Vector Search indexes where needed. No migration to PostgreSQL — MongoDB carries through. PostgreSQL is added in Track B for relational data only (models, routing logs, costs, personas).

4. **Python or Kotlin for Track B?** -- The `FORGE_OS_LOCAL_ARCHITECTURE_KOTLIN.md` spec is detailed and production-oriented. The `FORGE_OS_IMPLEMENTATION_GUIDE.md` also shows a Python path (FastAPI, ChromaDB). This decision doesn't block any work in this plan (all stepping stone work is Python), but should be resolved before Track B begins. Note: the database choice is now settled — MongoDB + VoyageAI for documents/vectors, PostgreSQL for relational data — regardless of whether Track B uses Python or Kotlin.

---

*This codebase is the bridge. Track A provides the intelligence (Claude Projects as personas). This codebase provides the memory, graph, and coordination. Track B eventually merges both into a single local system.*
