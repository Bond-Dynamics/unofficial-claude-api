# Improvement 1: Global Display IDs

## Priority: 1 (Highest)
## Effort: Medium
## Value: High

---

## Context & Motivation

The conversation archive (exchange_006) established that local IDs like `D001` are session-scoped -- two archives can have completely different `D001` decisions. The solution proposed was a **global display ID** in `PROJECT-TYPE-SEQUENCE` format (e.g., `FORGE-D-0042`). This makes entities human-memorable and globally unique across all archives and projects.

Currently, the only identifiers are:
- `local_id`: Session-scoped (e.g., `D001`) -- collides across archives
- `uuid`: UUIDv8 hex string -- globally unique but unreadable

There is no human-friendly globally unique identifier. Users must reference raw UUIDs when working cross-session.

---

## Architecture

```
                          ┌──────────────────────────┐
                          │  display_id_registry     │
                          │  (MongoDB collection)    │
                          │                          │
                          │  project_prefix: "FORGE" │
                          │  entity_type: "D"        │
                          │  next_sequence: 43       │
                          └──────────┬───────────────┘
                                     │
              ┌──────────────────────▼──────────────────────┐
              │ decision_registry.py / thread_registry.py    │
              │                                              │
              │ On insert: allocate_display_id("FORGE", "D") │
              │ → "FORGE-D-0043"                            │
              │ Stored as global_display_id field            │
              └──────────────────────────────────────────────┘
```

---

## Existing Code Surface

### Entity insert paths (where display IDs must be allocated)

| Module | Function | Entity Type Prefix |
|--------|----------|--------------------|
| `decision_registry.py:159` | `_insert_decision()` | `D` |
| `thread_registry.py:94-101` | `upsert_thread()` (insert branch) | `T` |

### Project name → prefix mapping (needs creation)

No prefix registry exists. Projects are identified by display name (`"Forge OS"`, `"The Nexus"`, etc.) in `conversation_registry.py:22-28`.

### Config (vectordb/config.py)

Will need a new collection constant: `COLLECTION_DISPLAY_ID_COUNTERS`.

### Scripts that output IDs (need display ID integration)

| Script | Where IDs appear |
|--------|------------------|
| `prepare_continuation.py:99` | `{d['local_id']}: {text_preview}` |
| `prepare_compression.py` | Decision/thread listings |
| `sync_compression.py:562-563` | `Decision {dec['local_id']}: {dec['text'][:80]}...` |

### API endpoints

| Endpoint | Module |
|----------|--------|
| `GET /api/forge/decisions` | `scripts/api_server.py` |
| `GET /api/forge/threads` | `scripts/api_server.py` |
| `forge_search` MCP tool | `scripts/mcp_server.py` |

---

## Files to Create

### 1. `vectordb/display_ids.py` (~120 lines)

Global display ID allocation and lookup.

```python
# --- Constants ---
# Default project prefix map (overridable via DB)
DEFAULT_PREFIX_MAP = {
    "Forge OS": "FORGE",
    "The Nexus": "NEXUS",
    "Reality Compiler": "RC",
    "Consciousness Physics": "CPHYS",
    "Wavelength": "WAVE",
    "Attention Currency": "ATTN",
}

ENTITY_PREFIXES = {"decision": "D", "thread": "T", "artifact": "A"}

# --- Public API ---

def allocate_display_id(project, entity_type, db=None):
    """Atomically allocate the next global display ID for a project + entity type.

    Uses MongoDB findAndModify with $inc for atomic counter increment.
    Returns: "FORGE-D-0043"
    """

def resolve_display_id(display_id, db=None):
    """Look up entity UUID by global display ID.

    Returns: {"uuid": "...", "collection": "decision_registry"} or None
    """

def get_project_prefix(project_name, db=None):
    """Get or create a prefix for a project name.

    Checks DB first, falls back to DEFAULT_PREFIX_MAP, finally
    auto-generates from first 4-5 chars uppercase.
    """

def register_display_id(display_id, entity_uuid, collection_name, db=None):
    """Record the mapping: display_id -> (uuid, collection).

    Called after allocation to enable reverse lookup.
    """

def bulk_backfill(project, entity_type, db=None):
    """Assign display IDs to all existing entities that lack one.

    Used for migration. Processes entities in created_at order so
    sequence numbers reflect chronological order.
    Returns: count of IDs assigned.
    """
```

### Schema: `display_id_counters` collection

```python
{
    "project_prefix": "FORGE",     # e.g., "FORGE", "NEXUS"
    "entity_type": "D",            # "D", "T", "A"
    "next_sequence": 43,           # Auto-incremented
}
```

### Schema: `display_id_index` collection

```python
{
    "display_id": "FORGE-D-0042",   # The human-readable ID
    "entity_uuid": "018d9a4b-...",  # UUIDv8 of the entity
    "collection": "decision_registry",
    "project": "Forge OS",
    "created_at": "2026-02-10T...",
}
```

---

## Files to Modify

### 2. `vectordb/config.py` (+3 lines)

```python
COLLECTION_DISPLAY_ID_COUNTERS = "display_id_counters"
COLLECTION_DISPLAY_ID_INDEX = "display_id_index"
```

### 3. `vectordb/decision_registry.py` (~+8 lines)

In `_insert_decision()` (line ~159):
- After `collection.insert_one(doc)`, call `allocate_display_id(project, "decision")`
- Store `global_display_id` in the document
- Register the mapping via `register_display_id()`

Add `global_display_id` to the document schema (line ~171).

### 4. `vectordb/thread_registry.py` (~+8 lines)

In `upsert_thread()` insert branch (line ~94):
- Same pattern as decisions: allocate + register on insert

Add `global_display_id` to the document schema (line ~72).

### 5. `scripts/prepare_continuation.py` (~+5 lines)

In `assemble_continuation_context()`:
- Replace `{d['local_id']}` with `{d.get('global_display_id', d['local_id'])}` in decision/thread output lines

### 6. `scripts/prepare_compression.py` (~+5 lines)

Same pattern: prefer `global_display_id` over `local_id` in output.

### 7. `scripts/sync_compression.py` (~+3 lines)

In CLI output: show `global_display_id` alongside `local_id` when available.

### 8. `vectordb/__init__.py` (~+3 lines)

Export `allocate_display_id`, `resolve_display_id` from `display_ids`.

---

## Implementation Phases

### Phase A: Core module + config

1. Add collection constants to `vectordb/config.py`
2. Create `vectordb/display_ids.py` with allocation, lookup, prefix mapping
3. Export from `vectordb/__init__.py`

**Depends on:** Nothing

### Phase B: Write path integration

1. Integrate into `_insert_decision()` in `decision_registry.py`
2. Integrate into `upsert_thread()` insert branch in `thread_registry.py`

**Depends on:** Phase A

### Phase C: Display path integration

1. Update `prepare_continuation.py` output to show global display IDs
2. Update `prepare_compression.py` output
3. Update `sync_compression.py` CLI output

**Depends on:** Phase A

### Phase D: Migration backfill

1. Add `bulk_backfill()` function to `display_ids.py`
2. Create `scripts/backfill_display_ids.py` CLI script
3. Run backfill for all existing decisions and threads

**Depends on:** Phases A + B

```
Phase A ──┬── Phase B ── Phase D
           └── Phase C
```

---

## Key Design Decisions

### Atomic counter via `findAndModify`

MongoDB's `findOneAndUpdate` with `$inc` is atomic -- no race conditions even with concurrent inserts. Returns the pre-increment value, so we get a clean sequence.

```python
result = counters.find_one_and_update(
    {"project_prefix": prefix, "entity_type": entity_type},
    {"$inc": {"next_sequence": 1}},
    upsert=True,
    return_document=ReturnDocument.AFTER,
)
sequence = result["next_sequence"]
```

### Zero-padded 4-digit sequence

`FORGE-D-0042` uses zero-padded 4-digit numbers. If a project exceeds 9999 entities of one type, it rolls to 5 digits (`FORGE-D-10000`). No truncation.

### Project prefix auto-generation

If a project isn't in `DEFAULT_PREFIX_MAP`, derive from name: `"Applied Alchemy"` -> `"AALCH"`. Store in DB so it's stable once generated.

### Display ID on insert only

Display IDs are assigned on first insert, never on update or validation. This preserves chronological ordering: lower sequence = older entity.

---

## Verification

```bash
# Phase A: Core module
python -c "
from vectordb.display_ids import allocate_display_id, resolve_display_id

# Allocate
did = allocate_display_id('Forge OS', 'decision')
print(f'Allocated: {did}')  # FORGE-D-0001

# Allocate another
did2 = allocate_display_id('Forge OS', 'decision')
print(f'Second: {did2}')  # FORGE-D-0002

# Different project
did3 = allocate_display_id('The Nexus', 'thread')
print(f'Nexus: {did3}')  # NEXUS-T-0001
"

# Phase D: Backfill
python scripts/backfill_display_ids.py --project "Forge OS" --dry-run
python scripts/backfill_display_ids.py --project "Forge OS"
```

---

## File Size Estimates

| File | Lines | Action |
|------|-------|--------|
| `vectordb/display_ids.py` | ~120 | Create |
| `scripts/backfill_display_ids.py` | ~60 | Create |
| `vectordb/config.py` | +3 | Modify |
| `vectordb/__init__.py` | +3 | Modify |
| `vectordb/decision_registry.py` | +8 | Modify |
| `vectordb/thread_registry.py` | +8 | Modify |
| `scripts/prepare_continuation.py` | +5 | Modify |
| `scripts/prepare_compression.py` | +5 | Modify |
| `scripts/sync_compression.py` | +3 | Modify |
| **Total** | **~215** | |
