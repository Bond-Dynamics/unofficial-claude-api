# Forge OS: Sync Pipeline (Layer 1.5-2)

## Purpose

The Sync Pipeline prevents **context rot** across compression hops. When a Claude Project conversation is compressed via `compress --lossless`, the resulting markdown archive contains decisions (D001...), threads (T001...), and metadata. Without this pipeline, those artifacts are orphaned — state drifts and prior decisions get silently dropped.

This pipeline captures compression archives into MongoDB registries, tracks which decisions/threads survive each hop, detects conflicts between decisions, and assembles structured context blocks for both compression and continuation.

---

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                  Claude Projects                     │
│                                                      │
│  compress --lossless  ──→  Markdown Archive          │
│                            (D001..., T001...)        │
└──────────────┬──────────────────────────────────────┘
               │
               │  pbpaste / --file
               ▼
┌─────────────────────────────────────────────────────┐
│              sync_compression.py                     │
│                                                      │
│  parse_archive(text) → {decisions, threads, meta}    │
│  sync_archive(parsed) → registries                   │
└──────────────┬──────────────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────────────┐
│              MongoDB (vectordb)                      │
│                                                      │
│  ┌──────────────────┐  ┌────────────────────┐       │
│  │ thread_registry   │  │ decision_registry   │      │
│  │ (CRUD + staleness)│  │ (CRUD + embed +     │      │
│  │                   │  │  conflict detect)   │      │
│  └──────────────────┘  └────────────────────┘       │
│                                                      │
│  ┌──────────────────┐  ┌────────────────────┐       │
│  │ lineage_edges     │  │ conflicts          │       │
│  │ (graph traversal) │  │ (two-signal detect)│       │
│  └──────────────────┘  └────────────────────┘       │
└──────────────┬──────────────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────────────┐
│              Context Assembly Scripts                 │
│                                                      │
│  prepare_continuation.py → clipboard (start session) │
│  prepare_compression.py  → clipboard (end session)   │
│  forge_session.sh        → full cycle walkthrough    │
└─────────────────────────────────────────────────────┘
```

---

## New Modules

### vectordb/thread_registry.py

Thread CRUD operations with deterministic UUIDv8 identity.

| Function | Description |
|----------|-------------|
| `upsert_thread()` | Insert or update a thread with deterministic UUID |
| `get_active_threads()` | All non-resolved threads, sorted by priority |
| `resolve_thread()` | Mark thread as resolved with resolution text |
| `get_stale_threads()` | Threads exceeding hop/day thresholds |
| `increment_thread_hops()` | Increment hops for threads absent from latest archive |

**Schema:** `uuid`, `local_id`, `title`, `status` (open/resolved/blocked), `project`, `project_uuid`, `priority` (high/medium/low), `blocked_by[]`, `resolution`, `epistemic_tier`, `hops_since_validated`, `last_validated`

### vectordb/decision_registry.py

Decision CRUD with auto-embedding via VoyageAI and conflict detection.

| Function | Description |
|----------|-------------|
| `upsert_decision()` | Three-path upsert: validate / update / insert |
| `get_active_decisions()` | All active decisions, sorted by epistemic tier |
| `get_stale_decisions()` | Decisions exceeding hop/day thresholds |
| `supersede_decision()` | Mark a decision as superseded by another |
| `increment_decision_hops()` | Increment hops for absent decisions |
| `find_similar_decisions()` | Vector search for similar decisions |

**Three upsert actions:**
- **validated**: Same UUID + same text_hash → reset hops, update timestamp
- **updated**: Same UUID + different text_hash → re-embed, full update
- **inserted**: New UUID → embed, run conflict detection

**Schema adds:** `text_hash` (SHA-256[:16]), `embedding` (1024-dim VoyageAI), `conflicts_with[]`, `dependents[]`, `superseded_by`, `rationale`

### vectordb/conflicts.py

Two-signal conflict detection between decisions.

| Function | Description |
|----------|-------------|
| `detect_conflicts()` | Run both signals against active decisions |
| `register_conflict()` | Record conflict via `$addToSet` on both documents |
| `_extract_entities()` | Regex extraction of D-IDs, T-IDs, project names |

**Signal 1 — Embedding similarity:** Cosine similarity > 0.85 with different text_hash indicates semantic overlap with different content (potential contradiction).

**Signal 2 — Entity-tier divergence:** Shared entity references (D-IDs, T-IDs, project names) between decisions with divergent epistemic tiers (delta > 0.2) indicates conflicting confidence levels about related topics.

### vectordb/compression_registry.py

Tracks every compression event as a first-class entity. Enables temporal queries ("show all compressions this week"), decision provenance ("what decisions came from this compression?"), checksum-based tamper detection, and branching support (one archive synced into multiple continuations).

| Function | Description |
|----------|-------------|
| `register_compression()` | Upsert by compression_tag; `$addToSet` for targets (branching) |
| `get_compression()` | Single record lookup by tag |
| `list_compressions()` | List events for a project, newest first |
| `verify_checksum()` | Compare stored vs computed SHA-256 |
| `compute_checksum()` | Standalone SHA-256 hex digest |

**Schema:** `compression_tag`, `project`, `source_conversation`, `target_conversations[]`, `decisions_captured[]`, `threads_captured[]`, `artifacts_captured[]`, `checksum` (SHA-256 hex), `metadata{}`, `created_at`, `updated_at`

**Branching:** When the same archive is synced into multiple continuation conversations, `register_compression()` uses `$addToSet` to append new targets to `target_conversations[]` without duplicating the record.

**Checksum verification:** `verify_checksum()` recomputes SHA-256 of the raw archive text and compares it against the stored checksum to detect post-sync modifications.

### vectordb/lineage.py

Directed graph of compression-hop relationships.

| Function | Description |
|----------|-------------|
| `add_edge()` | Create/update lineage edge with `$addToSet` for lists |
| `get_ancestors()` | Walk backward through lineage |
| `get_descendants()` | Walk forward through lineage |
| `get_lineage_chain()` | All edges for a compression tag |

**Schema:** `edge_uuid`, `source_conversation`, `target_conversation`, `compression_tag`, `decisions_carried[]`, `decisions_dropped[]`, `threads_carried[]`, `threads_resolved[]`

---

## Sync Scripts

### scripts/sync_compression.py

The critical bridge between markdown archives and MongoDB registries.

**Parser:** Handles two archive formats:
1. **Rich markdown** (primary): `### D001: Title` with `**Tier:**`, `**Decision:**`, etc.
2. **YAML blocks** (fallback): ````yaml decisions: - id: D001 ...```

**Sync engine:**
1. Upsert each decision (auto-embeds, detects conflicts)
2. Upsert each thread
3. Increment hops for items NOT in this archive
4. Create lineage edge if source conversation provided
5. Register compression tag with checksum and captured item lists
6. Emit `graph.sync.completed` event

**CLI:** `--project`, `--project-uuid`, `--file` | `--clipboard` | `--stdin`, `--conversation-id`, `--source-conversation-id`, `--dry-run`

### scripts/prepare_compression.py

Assembles pre-compression context from registries. Outputs structured block with Active Threads, Stale Warnings, Conflict Alerts. Copies to clipboard by default.

### scripts/prepare_continuation.py

Assembles continuation context for new conversations. Outputs Decisions In Force (grouped by tier), Open Threads, Warnings, Lineage. Copies to clipboard.

### scripts/forge_session.sh

Workflow wrapper with four commands:
- `start --project X` — prepare continuation context
- `compress --project X` — prepare compression context
- `sync --project X --project-uuid Y` — sync archive from clipboard
- `full --project X --project-uuid Y` — interactive full-cycle walkthrough

---

## Database Collections

Added to `vectordb/config.py`:

| Constant | Collection | Purpose |
|----------|------------|---------|
| `COLLECTION_THREAD_REGISTRY` | `thread_registry` | Thread lifecycle |
| `COLLECTION_DECISION_REGISTRY` | `decision_registry` | Decision lifecycle + embeddings |
| `COLLECTION_LINEAGE_EDGES` | `lineage_edges` | Compression-hop graph |
| `COLLECTION_COMPRESSION_REGISTRY` | `compression_registry` | Compression event tracking |

### Indexes (added to `ensure_forge_indexes()`)

**thread_registry:**
- Unique on `uuid`
- Compound `(project, status)`
- Compound `(status, updated_at)`

**decision_registry:**
- Unique on `uuid`
- Compound `(project, status)`
- On `text_hash`
- Compound `(status, last_validated)`
- Atlas Vector Search on `embedding` with `project` and `status` filters

**lineage_edges:**
- Unique on `edge_uuid`
- On `source_conversation`
- On `target_conversation`
- On `compression_tag`

**compression_registry:**
- Unique on `compression_tag`
- On `project`
- On `source_conversation`
- On `created_at`

---

## Staleness Model

Decisions and threads track `hops_since_validated` — incremented each sync for items NOT present in the archive. Items exceeding thresholds are flagged as stale:

| Threshold | Default | Config Constant |
|-----------|---------|-----------------|
| Max hops | 3 | `STALE_MAX_HOPS` |
| Max days | 30 | `STALE_MAX_DAYS` |

Stale items appear in Warnings sections of both compression and continuation context blocks.

---

## Usage

```bash
# Full session cycle
scripts/forge_session.sh full \
    --project "Forge OS" \
    --project-uuid "abc123-..."

# Sync a specific archive file
python scripts/sync_compression.py \
    --project "Forge OS" \
    --project-uuid "abc123-..." \
    --file data/artifacts/.../conversation_archive.md

# Dry run to inspect parsing
python scripts/sync_compression.py \
    --project "Forge OS" \
    --project-uuid "abc123-..." \
    --file data/artifacts/.../archive.md \
    --dry-run

# Prepare continuation context for new session
python scripts/prepare_continuation.py --project "Forge OS"

# Prepare compression context before compressing
python scripts/prepare_compression.py --project "Forge OS"
```

---

## Test Coverage

72 tests across 5 test modules:

| Module | Tests | Coverage |
|--------|-------|----------|
| `tests/test_thread_registry.py` | 11 | CRUD, deterministic UUID, sort, staleness, hops |
| `tests/test_decision_registry.py` | 10 | 3-path upsert, tier sort, supersession, hops |
| `tests/test_lineage.py` | 10 | Edge CRUD, ancestor/descendant traversal, order independence |
| `tests/test_sync_compression.py` | 27 | Both parser formats, artifacts, minimal/empty archives, sync engine, compression registration, dry run, lineage |
| `tests/test_compression_registry.py` | 15 | Register, get, list, verify/compute checksum, branching, upsert |

All tests use mocked database instances — no MongoDB required for testing.

---

## Patterns Followed

All modules follow established `vectordb/` patterns from `patterns.py`:

- `db=None` default → `get_database()` inside function
- `embed_texts([content[:8000]])` for embedding
- `$vectorSearch` aggregation pipeline for similarity
- `emit_event()` for audit logging
- Return dicts with `action` field
- `$set` for upserts, `$addToSet` for list appends, `$inc` for counters
- ISO 8601 strings for `created_at`/`updated_at`
- Deterministic UUIDv8 via `vectordb.uuidv8` functions
