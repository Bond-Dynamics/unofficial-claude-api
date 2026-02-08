# Context Rot Assessment: Compression Skill + VectorDB for Forge OS

**Date:** 2026-02-08
**Status:** Analysis complete, implementation pending
**Scope:** context-compression skill, vectordb memory layer, Forge OS Layer 1

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

---

## Proposed Architecture

The compression skill becomes the **interface layer**, the vectordb becomes the **persistence layer**:

```
  Compression Skill (interface)
  ┌──────────────────────────────────────────────────┐
  │                                                  │
  │  compress --lossless                             │
  │    1. Query vectordb for active threads           │
  │    2. Query vectordb for stale decisions          │
  │    3. Detect cross-project conflicts              │
  │    4. Generate archive WITH current state          │
  │    5. Register lineage edge in vectordb           │
  │    6. Sync thread/decision state to vectordb      │
  │                                                  │
  │  New conversation (continuation)                 │
  │    1. Paste archive -> skill detects continuation │
  │    2. Register lineage edge                       │
  │    3. Pull CURRENT thread state from vectordb     │
  │       (not stale state from archive text)         │
  │    4. Surface relevant cross-project decisions    │
  │    5. Flag decisions needing revalidation          │
  │                                                  │
  └──────────────────┬───────────────────────────────┘
                     │
                     ▼
  VectorDB (persistence)
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

**Key principle:** The archive text in the continuation prompt becomes a **cache**, not the source of truth. The vectordb is the source of truth. If the archive says T001 is open but the vectordb says it was resolved in a different conversation, the vectordb wins.

This is the "transformer layer" — the vectordb acts as the cross-attention mechanism across sandboxed projects, and the compression skill is the query/key/value encoding.

---

## New Collections Schema

### `lineage`

Conversation graph edges. Each document represents one compression-continuation link.

```
{
  "lineage_id":              "lin_<hex12>",
  "source_conversation_id":  "<uuid>",       // conversation that was compressed
  "target_conversation_id":  "<uuid>",       // continuation conversation
  "compression_tag":         "TOPIC_A_RESULT",
  "compression_mode":        "lossless | lossy | partial",
  "compressed_at":           "<ISO 8601>",
  "turn_range":              [1, 35],         // turns compressed (null = all)
  "decisions_carried":       ["D001", "D002"],
  "decisions_dropped":       ["D003"],
  "threads_carried":         ["T001"],
  "threads_resolved":        ["T002"],
  "project_name":            "The Nexus",
  "project_uuid":            "<uuid>",
  "bridge_summary":          "<1-2 paragraph summary of what changed>"
}
```

Indexes: `source_conversation_id`, `target_conversation_id`, `compression_tag`, `project_name`.

### `threads`

Global thread registry. Single source of truth for open/resolved status.

```
{
  "thread_id":       "thr_<hex12>",       // globally unique
  "local_id":        "T001",              // the ID used in compression text
  "title":           "Design pagination strategy",
  "status":          "open | resolved | superseded | abandoned",
  "priority":        "high | medium | low",
  "blocked_by":      ["thr_<hex12>"],     // other thread IDs
  "first_seen_in":   "<conversation_uuid>",
  "resolved_in":     "<conversation_uuid> | null",
  "conversation_ids": ["<uuid>", "<uuid>"],  // every conversation mentioning it
  "project_name":    "The Nexus",
  "project_uuid":    "<uuid>",
  "content":         "Full description of the thread",
  "resolution":      "How it was resolved (null if open)",
  "embedding":       [1024 floats],       // for semantic search
  "created_at":      "<ISO 8601>",
  "updated_at":      "<ISO 8601>",
  "tags":            ["pagination", "api-design"]
}
```

Indexes: `thread_id` (unique), `status`, `project_name`, `first_seen_in`. Vector index on `embedding` with `status` and `project_name` as filter fields.

### `decisions`

Global decision registry with provenance and conflict detection.

```
{
  "decision_id":         "dec_<hex12>",     // globally unique
  "local_id":            "D001",            // the ID used in compression text
  "decision":            "Use UUID v7 for all resource IDs",
  "rationale":           "Sortable, no coordination required, K-sortable",
  "epistemic_tier":      0.85,
  "status":              "active | revised | superseded | invalidated",
  "originated_in":       "<conversation_uuid>",
  "revised_in":          "<conversation_uuid> | null",
  "superseded_by":       "dec_<hex12> | null",
  "conversation_ids":    ["<uuid>", "<uuid>"],
  "project_name":        "The Nexus",
  "project_uuid":        "<uuid>",
  "dependencies":        ["dec_<hex12>"],    // decisions this builds on
  "dependents":          ["dec_<hex12>"],    // decisions that depend on this
  "alternatives_rejected": ["auto-increment", "UUID v4"],
  "embedding":           [1024 floats],
  "created_at":          "<ISO 8601>",
  "last_validated":      "<ISO 8601>",      // for decay detection
  "validation_count":    3,                 // times carried forward
  "tags":                ["database", "identifiers"]
}
```

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

1. **VectorDB: new collections + functions** — Add `lineage`, `threads`, `decisions` collections to `config.py` and `db.py`. Create `vectordb/lineage.py`, `vectordb/threads.py`, `vectordb/decisions.py` with the functions described above.

2. **Pipeline: auto-detection** — Enhance `vectordb/pipeline.py` to detect compressed archives, extract thread/decision references, and populate the new collections during ingestion.

3. **Context load: enhanced assembly** — Update `vectordb/context.py` to include active threads and relevant decisions in assembled context, with cross-project search support.

4. **Skill: vectordb integration** — Update the compression skill schema to query vectordb before compressing, sync state after compressing, and include revalidation/cross-project sections.

5. **Search: new scopes** — Update `scripts/search.py` with `--scope threads`, `--scope decisions`, `--scope lineage` options.

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
