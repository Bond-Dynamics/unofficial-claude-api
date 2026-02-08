# Context Rot Assessment: Compression Skill + VectorDB for Forge OS

**Date:** 2026-02-08
**Updated:** 2026-02-08 (incorporated external review + UUIDv8 deterministic ID system for bootstrap problem)
**Status:** Analysis complete, implementation pending
**Scope:** context-compression skill, vectordb memory layer, Forge OS Layer 1
**Review:** Assessed at epistemic tier ~0.85 by external LLM review

---

## Problem Statement

Compressed archives produced by `context-compression` are write-once text blobs. They encode conversation state accurately at compression time, but context degrades ("rots") across multiple compression hops and parallel project branches. The user reports getting lost between the compressed artifact and the continuation that consumes it — the "bridge" is unclear.

The root cause: the compression skill is a **stateless encoder** with no external persistence. Every archive is a dead end. Decisions, threads, and lineage exist only as text inside the conversation they were pasted into.

---

## Where Context Rot Happens

### 1. The Compression Boundary (write side)

When `compress --lossless` runs, the skill produces a structured archive with D001, T001, A001 IDs. But those IDs are **local to that compression** — they don't exist anywhere outside the text artifact. Decision D003 in one conversation has no relationship to D003 in another. There is no registry.

### 2. The Bridge Gap (transfer)

The user skims the archive and pastes it into a new conversation. The new Claude instance sees the continuation prompt and treats inherited decisions as ground truth. But:

- **Thread status is stale** — T001 may say "OPEN" in the archive, but it was resolved two conversations ago in a different project
- **Decisions conflict silently** — D002 in The Nexus might contradict D005 in The Reality Compiler, but nothing cross-references them
- **Lineage is lost** — the new conversation has no idea it's the 4th link in a chain. If the user asks "why did we decide X?", Claude can only search the pasted text, not the actual source conversation

### 3. The Accumulation Problem (read side)

After 3-4 compression hops, inherited context becomes a game of telephone. Each compression selectively carries forward from the previous one. The epistemic tier system helps, but it cannot catch **drift** — a 0.7 heuristic that was true 3 compressions ago might now be invalidated by work done in a parallel conversation.

---

## What the Skill Gets Right

These elements should be preserved in any enhancement:

| Element | Why It Works |
|---------|-------------|
| Structured IDs (D001, T001, A001) | Right unit of tracking — discrete, referenceable |
| Epistemic tiering (0.0-1.0) | Prevents speculation from calcifying into "facts" |
| Partial compression with `--context` | Correct model for selective inheritance |
| Compression lineage table | Exactly the metadata that needs external persistence |
| Retrieval protocol | Right idea — just needs a real backend |
| Priority-ordered preservation | Critical > High > Medium > Low is sound triage |

---

## What's Missing for Forge OS

### Gap 1: No Conversation Graph

The `compression_lineage` table in the lossless schema tracks parent-child relationships, but it's embedded in the archive text. The vectordb has no `conversation_lineage` collection. When conversation C inherits from B which inherits from A, that chain is invisible to any system-level query.

**What Forge OS needs:** A `lineage` collection where each edge stores: source conversation ID, target conversation ID, the compression tag, which decisions/threads were carried forward, and which were dropped.

### Gap 2: No Thread Registry

Open threads (T001, T002) are local to each compression. Thread T001 in conversation A might be "Design pagination strategy." It gets resolved in conversation B. But if conversation C inherits from A (not B), T001 shows up as still open. There is no single source of truth for thread state.

**What Forge OS needs:** A `threads` collection where each thread has a globally unique ID, a status (open/resolved/superseded/abandoned), and a list of every conversation it appears in. When compressing, the skill checks the registry: "Is this thread actually still open?"

### Gap 3: No Decision Registry

Same problem as threads. Decision D002 is local text. If it gets revised in a later conversation, the original archive still contains the old version. There is no way to detect conflicts between decisions made in parallel conversations across different projects.

**What Forge OS needs:** A `decisions` collection with: globally unique ID, the decision text, epistemic tier, the conversation it originated in, any conversations that revised or superseded it, and an embedding for semantic search ("find all decisions about authentication").

### Gap 4: Retrieval Protocol Has No Backend

The skill defines retrieval commands like "Why did we decide X?" and "Show earlier version of [artifact]" — but these are instructions for Claude to search through the pasted archive text. There is no actual system backing them. The vectordb already has `vector_search` and `context_load`, but they don't know about decisions, threads, or lineage.

**What Forge OS needs:** `context_load` enhanced to query the thread/decision registries. When a new conversation starts with a pasted archive, the retrieval protocol should hit the vectordb, not just grep through the pasted text.

### Gap 5: No Decay Detection

A decision made 4 months and 8 compressions ago with tier 0.6 is probably stale. But the skill has no mechanism to flag this. Epistemic tiers are assigned once and never revisited.

**What Forge OS needs:** A `last_validated` timestamp on decisions. If a decision hasn't been touched in N compressions or M days, flag it for review during the next compression. The skill should output a "Decisions needing revalidation" section.

### Gap 6: No Cross-Project Awareness

This is the core sandboxing problem. The Nexus, The Reality Compiler, Applied Alchemy — each produces compressions independently. But decisions in one project affect others. The skill has no concept of "check what other projects decided about this topic."

**What Forge OS needs:** The thread and decision registries should be **project-aware but globally searchable**. When compressing in The Nexus, the skill should surface: "Decision D012 in Applied Alchemy is relevant to your current thread T003."

### Gap 7: No ID Bootstrap Protocol

The entire lineage graph depends on stable, unique identifiers for conversations, decisions, threads, and lineage edges. But the compression skill runs inside Claude's context window — there is no reliable way to capture the current conversation's UUID at compression time. The `source_conversation_id` field in the lineage schema is load-bearing infrastructure with no defined capture mechanism.

The conversation UUID exists in three places:

1. **Claude's API response** — the `uuid` field on each `chat_conversation` object, available to `fetch_conversations.py` during sync
2. **The browser URL** — `claude.ai/chat/{uuid}`, visible to the user but not to Claude
3. **The sync cron job** — fetches and stores IDs during ingestion from Claude's API

**Resolution: UUIDv8 as Deterministic ID System**

UUIDv8 (RFC 9562) solves the bootstrap problem by making IDs **deterministic and derivable** from known inputs, rather than requiring a central authority to assign them. The format:

```
[48-bit timestamp (ms)] [4-bit version=8] [2-bit variant] [74-bit suffix]
                                                            └─ SHA-256(namespace_uuid + timestamp_bytes)[:10]
```

This gives two critical properties:
- **Time-ordered** — IDs sort chronologically by creation time
- **Deterministic** — same inputs always produce the same ID. An ID can be reconstructed from source data without any central registry.

**ID derivation for Forge OS entities:**

| Entity | Namespace | Deterministic Input | Example |
|--------|-----------|-------------------|---------|
| Conversation | `project_uuid` | `conversation_name + creation_timestamp` | Stable across re-syncs — same conversation always gets the same ID |
| Compression tag | `project_uuid` | `conversation_id + compression_timestamp + turn_range` | Tags become derivable, not just semantic labels |
| Thread | `project_uuid` | `thread_title + first_seen_conversation_id` | Same thread discovered independently in two syncs → same ID |
| Decision | `project_uuid` | `decision_text_hash + originated_conversation_id` | Content-addressable — same decision = same ID |
| Lineage edge | N/A | `compositePair(source_conv_id, target_conv_id)` | Order-independent pair ID (A→B and B→A produce the same edge ID) |

**Why this matters:**

1. **Self-bootstrapping graph** — the sync pipeline no longer needs to be the sole ID authority. Any process that has the same inputs can independently derive the same ID. The lineage graph can be built by the sync cron, a pre-processing script, or reconstructed from raw conversation data — all producing identical IDs.

2. **Free deduplication** — if the same conversation is fetched twice, it produces the same UUIDv8. If the same decision is extracted by two different pipeline runs, it gets the same decision ID. No dedup logic needed.

3. **Retroactive lineage still works** — the sync pipeline scans for compression tags in message content and builds lineage edges, but now the edge IDs are deterministic. Re-running the pipeline produces the same graph, not duplicate edges.

4. **Cross-device consistency** — if the user runs `prepare_compression.py` on a laptop and the sync cron runs on a server, both derive the same IDs for the same entities. No coordination needed.

The `BASE_UUID` for the Forge OS namespace is derived via UUIDv5: `UUIDv5(DNS_NAMESPACE, "forgeos.local")`. All project UUIDs are derived from this base. The derivation chain is fully deterministic from a single root.

The `compositePair(a, b)` function (from the Cheeky UUIDv8 implementation) is particularly valuable for lineage edges — it produces the same ID regardless of which conversation is "source" and which is "target," preventing duplicate edges when the relationship is discovered from either direction.

### Gap 8: No Conflict Resolution Policy

The assessment states "the vectordb wins" when archive state conflicts with registry state. But the vectordb itself can have conflicts — two parallel conversations may independently revise the same decision, or resolve the same thread differently. Without a conflict resolution policy, the registry becomes a last-write-wins system that silently drops one side of a conflict.

**Resolution:** Define explicit conflict resolution semantics:

| Scenario | Resolution |
|----------|------------|
| Archive says OPEN, registry says RESOLVED | Registry wins (more recent state) |
| Two active revisions of the same decision | Surface both to user, block auto-carry-forward until resolved |
| Decision dependency chain broken by revision | Flag all dependent decisions for revalidation |
| Cross-project contradiction (same topic, different conclusions) | Surface as conflict, never auto-resolve — user must choose |
| Tier mismatch (0.85 vs 0.3 on same topic) | Higher tier wins if same project; surface both if cross-project |

The `decisions` collection needs a `conflicts_with` field — a list of `dec_<hex12>` IDs that semantically contradict this decision. Conflict detection runs during pipeline ingestion: when a new decision is registered, vector search the existing active decisions. If similarity > 0.85 but the decision text implies a different conclusion, register a conflict edge on both documents.

The compression skill, when generating the archive, must include a `## Conflicts` section if any active decisions have unresolved conflicts.

### Gap 9: Runtime Access — The Skill Cannot Query the VectorDB

The proposed architecture has the compression skill calling `vectordb.threads.thread_active()` and `vectordb.decisions.decision_search()`. But the skill is a prompt specification that runs inside Claude's context window. Claude cannot make MongoDB queries at runtime. The skill has no network access to the vectordb.

**Resolution:** Separate the specification layer from the execution layer. The skill remains a prompt specification — it defines WHAT to compress and HOW to structure it. The vectordb querying happens in a **pre-processing script** that runs before Claude sees the compression prompt.

The flow becomes:

```
User wants to compress
  1. User runs: python3 scripts/prepare_compression.py --project "The Nexus"
     → Script queries vectordb for active threads, stale decisions, conflicts
     → Script generates a "registry state" block as structured text
  2. User pastes registry state into conversation alongside "compress --lossless"
     → Claude sees current thread/decision state from the registry
     → Claude compresses with accurate state, not stale archive text
  3. User runs: python3 scripts/sync_compression.py --archive <pasted archive text>
     → Script parses the compression output
     → Script syncs new decisions, thread updates, lineage edges to vectordb
```

This preserves the skill as a Claude-native prompt specification while the tooling around it handles persistence. The pre/post scripts are thin wrappers around the vectordb functions.

For the continuation side, the same pattern applies:

```
User starts a new conversation from a compressed archive
  1. User runs: python3 scripts/prepare_continuation.py --tag "TOPIC_A_RESULT"
     → Script pulls current thread state, relevant cross-project decisions, decay flags
     → Script generates an "updated context" block
  2. User pastes both the original archive AND the updated context block
     → Claude sees the archive (cache) plus current registry state (source of truth)
     → Conflicts between archive and registry are visible in the updated context block
```

This is architecturally the same as option (c) from the external review: the sync pipeline populates context before Claude sees it.

---

## Proposed Architecture

The compression skill becomes the **interface layer**, the vectordb becomes the **persistence layer**, and pre/post scripts become the **sync layer**:

```
  Compression Skill (specification layer — runs inside Claude)
  ┌──────────────────────────────────────────────────┐
  │                                                  │
  │  compress --lossless                             │
  │    - Reads registry state block (provided by      │
  │      pre-processing script, not direct DB query)  │
  │    - Generates archive with current state         │
  │    - Includes conflicts, decay flags,             │
  │      cross-project context from registry block    │
  │                                                  │
  │  New conversation (continuation)                 │
  │    - Reads archive (cache) + updated context      │
  │      block (source of truth from registry)        │
  │    - Registry state overrides stale archive text  │
  │                                                  │
  └──────────────────┬───────────────────────────────┘
                     │
                     │ user copies archive text
                     ▼
  Pre/Post Scripts (sync layer — runs on local machine)
  ┌──────────────────────────────────────────────────┐
  │                                                  │
  │  prepare_compression.py                          │
  │    - Queries vectordb for active threads          │
  │    - Queries for stale decisions, conflicts       │
  │    - Generates "registry state" text block        │
  │    - User pastes into Claude before compressing   │
  │                                                  │
  │  sync_compression.py                             │
  │    - Parses compression archive output            │
  │    - Registers new decisions, thread updates      │
  │    - Detects conflicts via semantic similarity    │
  │    - Lineage edges built by pipeline ingestion    │
  │                                                  │
  │  prepare_continuation.py                         │
  │    - Pulls current thread/decision state by tag   │
  │    - Generates "updated context" block            │
  │    - User pastes alongside archive into new chat  │
  │                                                  │
  └──────────────────┬───────────────────────────────┘
                     │
                     ▼
  VectorDB (persistence layer)
  ┌──────────────────────────────────────────────────┐
  │                                                  │
  │  Existing collections:                           │
  │    messages, conversations, documents,            │
  │    patterns, scratchpad, archive, events           │
  │                                                  │
  │  New collections:                                │
  │    lineage    - conversation graph edges          │
  │    threads    - global thread registry            │
  │    decisions  - global decision registry          │
  │                 (embedded for semantic search)     │
  │                                                  │
  └──────────────────────────────────────────────────┘
```

**Key principles:**

1. **Archives are caches, not sources of truth.** The vectordb is the source of truth. If the archive says T001 is open but the vectordb says it was resolved in a different conversation, the vectordb wins.

2. **The skill is a specification, not an executor.** Claude defines WHAT to compress and HOW to structure it. The pre/post scripts handle persistence — Claude never queries MongoDB directly.

3. **IDs are deterministic and derivable via UUIDv8.** Every entity (conversation, thread, decision, lineage edge) gets a UUIDv8 derived from known inputs — namespace + timestamp + content hash. The sync pipeline, pre/post scripts, and any future process can independently derive the same IDs from the same data. No central ID authority needed. Lineage edges use `compositePair()` for order-independent deduplication.

4. **Conflicts are surfaced, not silently resolved.** Cross-project contradictions and parallel decision revisions are presented to the user. Only trivially resolvable conflicts (tier 0.85 vs tier 0.3 within the same project) can be auto-resolved.

This is the "transformer layer" — the vectordb acts as the cross-attention mechanism across sandboxed projects, and the compression skill is the query/key/value encoding.

---

## New Collections Schema

### `lineage`

Conversation graph edges. Each document represents one compression-continuation link.

```
{
  "lineage_id":              "<uuidv8>",     // compositePair(source_id, target_id) — order-independent
  "source_conversation_id":  "<uuidv8>",     // conversation that was compressed
  "target_conversation_id":  "<uuidv8>",     // continuation conversation
  "compression_tag":         "TOPIC_A_RESULT",
  "compression_mode":        "lossless | lossy | partial",
  "compressed_at":           "<ISO 8601>",
  "turn_range":              [1, 35],         // turns compressed (null = all)
  "decisions_carried":       ["D001", "D002"],
  "decisions_dropped":       ["D003"],
  "threads_carried":         ["T001"],
  "threads_resolved":        ["T002"],
  "project_name":            "The Nexus",
  "project_uuid":            "<uuidv8>",
  "bridge_summary":          "<1-2 paragraph summary of what changed>"
}
```

All IDs are UUIDv8 — deterministic and derivable. `lineage_id` uses `compositePair()` so the same edge discovered from either direction produces the same ID. Re-running the pipeline never creates duplicate edges.

Indexes: `source_conversation_id`, `target_conversation_id`, `compression_tag`, `project_name`.

### `threads`

Global thread registry. Single source of truth for open/resolved status.

```
{
  "thread_id":       "<uuidv8>",          // UUIDv8(project_uuid, thread_title + first_seen_conv_id)
  "local_id":        "T001",              // the ID used in compression text
  "title":           "Design pagination strategy",
  "status":          "open | resolved | superseded | abandoned",
  "priority":        "high | medium | low",
  "blocked_by":      ["<uuidv8>"],        // other thread IDs
  "first_seen_in":   "<uuidv8>",          // conversation UUIDv8
  "resolved_in":     "<uuidv8> | null",
  "conversation_ids": ["<uuidv8>", "<uuidv8>"],  // every conversation mentioning it
  "project_name":    "The Nexus",
  "project_uuid":    "<uuidv8>",
  "content":         "Full description of the thread",
  "resolution":      "How it was resolved (null if open)",
  "embedding":       [1024 floats],       // for semantic search
  "created_at":      "<ISO 8601>",
  "updated_at":      "<ISO 8601>",
  "tags":            ["pagination", "api-design"]
}
```

Thread IDs are deterministic: `UUIDv8(namespace=project_uuid, content=thread_title + first_seen_conversation_id)`. If the same thread is extracted independently by two pipeline runs, it gets the same ID — no dedup needed.

Indexes: `thread_id` (unique), `status`, `project_name`, `first_seen_in`. Vector index on `embedding` with `status` and `project_name` as filter fields.

### `decisions`

Global decision registry with provenance and conflict detection.

```
{
  "decision_id":         "<uuidv8>",        // UUIDv8(project_uuid, decision_text_hash + originated_conv_id)
  "local_id":            "D001",            // the ID used in compression text
  "decision":            "Use UUID v7 for all resource IDs",
  "rationale":           "Sortable, no coordination required, K-sortable",
  "epistemic_tier":      0.85,
  "status":              "active | revised | superseded | invalidated",
  "originated_in":       "<uuidv8>",
  "revised_in":          "<uuidv8> | null",
  "superseded_by":       "<uuidv8> | null",
  "conversation_ids":    ["<uuidv8>", "<uuidv8>"],
  "project_name":        "The Nexus",
  "project_uuid":        "<uuidv8>",
  "dependencies":        ["<uuidv8>"],      // decisions this builds on
  "dependents":          ["<uuidv8>"],      // decisions that depend on this
  "conflicts_with":      ["<uuidv8>"],      // semantically contradicting decisions
  "alternatives_rejected": ["auto-increment", "UUID v4"],
  "embedding":           [1024 floats],
  "created_at":          "<ISO 8601>",
  "last_validated":      "<ISO 8601>",      // for decay detection
  "validation_count":    3,                 // times carried forward
  "tags":                ["database", "identifiers"]
}
```

Decision IDs are content-addressable: `UUIDv8(namespace=project_uuid, content=SHA256(decision_text) + originated_conversation_id)`. Same decision text originating from the same conversation always produces the same ID. A revised decision gets a new ID (different text), with the original linked via `superseded_by`.

Indexes: `decision_id` (unique), `status`, `project_name`, `epistemic_tier`, `originated_in`. Vector index on `embedding` with `status` and `project_name` as filter fields.

---

## New VectorDB Functions

### Lineage

```python
lineage_link(source_id, target_id, compression_tag, bridge_summary, ...)
    # Register a compression-continuation edge

lineage_trace(conversation_id, direction="both")
    # Return the full chain: all ancestors and descendants

lineage_bridge(source_id, target_id)
    # Generate a bridge summary: what changed between two linked conversations
```

### Threads

```python
thread_create(title, local_id, conversation_id, project_name, ...)
    # Register a new thread

thread_update(thread_id, status=None, resolution=None, conversation_id=None, ...)
    # Update status, add conversation reference

thread_active(project_name=None)
    # Get all open threads, optionally filtered by project

thread_search(query, status="open", project_name=None)
    # Semantic search across threads
```

### Decisions

```python
decision_create(decision, rationale, tier, local_id, conversation_id, ...)
    # Register a new decision

decision_revise(decision_id, new_decision, new_rationale, conversation_id, ...)
    # Revise a decision, preserving the original

decision_search(query, status="active", project_name=None)
    # Semantic search for relevant decisions

decision_stale(days=30, max_tier=0.7)
    # Find decisions that haven't been validated recently

decision_conflicts(decision_id=None, project_name=None)
    # Find unresolved conflicts — decisions with non-empty conflicts_with
    # If decision_id given, return conflicts for that decision
    # If project_name given, return all conflicts involving that project

decision_resolve_conflict(decision_id, keep_id, reason)
    # Resolve a conflict: supersede the losing decision, log the reason
```

### Enhanced Context Load

```python
context_load(query, project_name=None, include_threads=True, include_decisions=True,
             cross_project=False, ...)
    # Assemble context from ALL sources including threads/decisions
    # cross_project=True searches across all projects
```

---

## Pipeline Integration

The embedding pipeline (`vectordb/pipeline.py`) should be enhanced to auto-detect lineage, threads, and decisions during conversation ingestion:

1. **Lineage detection** — scan first message of each conversation for compressed archives (text attachments matching the continuation prompt format). If found, register a lineage edge to the source conversation.

2. **Thread extraction** — scan messages for thread-like patterns: "T001", "OPEN", "resolved", "next step", "blocked by". Register or update threads in the registry.

3. **Decision extraction** — scan messages for decision patterns: "D001", "decided", "we chose", "rationale". Register or update decisions in the registry.

This makes the sync cron job (`scripts/sync_claude.sh`) automatically build the conversation graph, thread registry, and decision registry every time it runs.

---

## Compression Skill Updates

### On `compress --lossless`:

1. **Before compressing:** Query vectordb for current state of all inherited threads and decisions. Use vectordb state, not stale archive text.
2. **Cross-project check:** Search decisions collection for semantically similar decisions in other projects. Surface conflicts.
3. **Decay check:** Query `decision_stale()` for decisions needing revalidation. Add a "Decisions Needing Revalidation" section to the archive.
4. **After compressing:** Sync compression results to vectordb — register lineage edge, update thread statuses, register new decisions, bump `last_validated` on carried decisions.

### New archive section: `## Revalidation Required`

```markdown
## Revalidation Required

The following inherited decisions have not been validated in 30+ days
or 3+ compression hops. Review before carrying forward:

| ID | Decision | Tier | Last Validated | Hops Since |
|----|----------|------|----------------|------------|
| D003 | Attention operates as a fundamental field | 0.4 | 2026-01-05 | 4 |
| D011 | Dual-track curriculum | 0.8 | 2026-01-20 | 2 |
```

### New archive section: `## Cross-Project Context`

```markdown
## Cross-Project Context

Decisions from other projects relevant to current threads:

| Source Project | Decision | Tier | Relevance |
|---------------|----------|------|-----------|
| Applied Alchemy | D012: Math program as Codebreaker core module | 0.6 | Overlaps with T003 (curriculum design) |
| The Reality Compiler | D005: Topology required for formalization | 0.6 | Constrains T005 (topic mapping) |
```

### New archive section: `## Conflicts`

```markdown
## Conflicts

The following active decisions have unresolved contradictions.
These MUST be resolved before carrying forward — do not inherit both sides.

| Decision A | Decision B | Project A | Project B | Nature |
|-----------|-----------|-----------|-----------|--------|
| D002: Use REST for all APIs (0.7) | D005: Use GraphQL for client-facing APIs (0.5) | The Nexus | Reality Compiler | Contradictory API strategy |
| D008: JWT for auth (0.8) | D014: Session cookies for auth (0.6) | Bond Dynamics | Cheeky | Contradictory auth mechanism |

Action required: choose one side per conflict, or define scoping rules
(e.g., "REST for internal, GraphQL for client-facing").
```

### Updated `external_store` config:

```yaml
external_store:
  type: vector_db
  location: mongodb://localhost:27017/claude_vectordb
  contains:
    - full_transcript: true
    - artifact_versions: all
    - rationale_chains: full
    - prior_compressions: [list of prior tags]
  sync:
    - lineage: registered
    - threads: synced
    - decisions: synced
    - last_validated: bumped
```

---

## Implementation Order

0. **UUIDv8 ID system + conflict resolution policy** — Implement the UUIDv8 generator with Forge OS `BASE_UUID = UUIDv5(DNS_NAMESPACE, "forgeos.local")` as the root namespace. Define derivation functions for conversation IDs, thread IDs, decision IDs, and lineage edge IDs (via `compositePair`). Define conflict resolution semantics as specified in Gap 8. This is load-bearing — the entire graph depends on deterministic, derivable IDs.

1. **VectorDB: new collections + functions** — Add `lineage`, `threads`, `decisions` collections to `config.py` and `db.py`. Create `vectordb/lineage.py`, `vectordb/threads.py`, `vectordb/decisions.py` with the functions described above, including `conflicts_with` field and conflict detection via semantic similarity during registration.

2. **Pipeline: auto-detection** — Enhance `vectordb/pipeline.py` to detect compressed archives, extract thread/decision references, and populate the new collections during ingestion. Lineage edges are built here by scanning for compression tags and continuation patterns in message content.

3. **Context load: enhanced assembly** — Update `vectordb/context.py` to include active threads and relevant decisions in assembled context, with cross-project search support.

4. **Pre/post scripts** — Create `scripts/prepare_compression.py`, `scripts/sync_compression.py`, and `scripts/prepare_continuation.py`. These are the sync layer between Claude (specification) and the vectordb (persistence). The skill itself only needs new archive sections (Revalidation Required, Cross-Project Context, Conflicts) — the actual vectordb querying happens in the scripts, not in the skill.

5. **Search: new scopes** — Update `scripts/search.py` with `--scope threads`, `--scope decisions`, `--scope lineage` options.

6. **Skill: schema update** — Update the compression skill to expect registry state blocks as input and to include the new archive sections. Minimal changes — the skill remains a prompt specification, not an executor.

---

## Verification

After implementation:

```bash
# Verify lineage detection
python3 -c "
from vectordb.lineage import lineage_trace
chain = lineage_trace('48ff6473-c514-4942-9177-33a2aaeb3583')
print(f'Chain length: {len(chain)}')
for edge in chain:
    print(f'  {edge[\"compression_tag\"]}: {edge[\"source_conversation_id\"][:8]} -> {edge[\"target_conversation_id\"][:8]}')
"

# Verify active threads
python3 -c "
from vectordb.threads import thread_active
open_threads = thread_active()
print(f'Open threads: {len(open_threads)}')
for t in open_threads[:5]:
    print(f'  [{t[\"priority\"]}] {t[\"title\"]} (project: {t[\"project_name\"]})')
"

# Verify decision search
python3 -c "
from vectordb.decisions import decision_search
results = decision_search('authentication approach')
for d in results[:3]:
    print(f'  [{d[\"epistemic_tier\"]}] {d[\"decision\"]} (project: {d[\"project_name\"]})')
"

# Verify stale decision detection
python3 -c "
from vectordb.decisions import decision_stale
stale = decision_stale(days=30)
print(f'Stale decisions: {len(stale)}')
"

# Verify cross-project context
python3 -c "
from vectordb.context import context_load
ctx = context_load('curriculum design', cross_project=True)
print(ctx['context_text'][:500])
"
```
