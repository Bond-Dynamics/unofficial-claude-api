# Improvement 2: Explicit Dual-Identity Model

## Priority: 2
## Effort: Medium
## Value: High

---

## Context & Motivation

The conversation archive (exchange_006) established a **dual-identity model** where each entity has two distinct identifiers:

| Identity | Derived From | Purpose |
|----------|--------------|---------|
| **Instance ID** | `UUIDv8(conversation_id, local_id)` | "Where did this appear?" |
| **Canonical ID** | `UUIDv8(project_id, content_hash)` | "What decision is this?" |

The current implementation conflates these into a single `uuid` field derived from `(project_uuid, text_hash, originated_conversation_id)` via `decision_id()` in `uuidv8.py:251-274`. This means:

- The same decision restated in a new archive gets a **different** UUID (different conversation_id)
- There's no way to query "show me all mentions of this canonical decision across archives"
- The `instances` array from the archive design (multiple appearances of the same decision) doesn't exist

The core problem: the current UUID is partially content-addressed but also conversation-scoped, making it neither a pure instance ID nor a pure canonical ID.

---

## Architecture

```
              Current (single identity)
              ┌─────────────────────────────────┐
              │ uuid = f(project, text, conv_id) │
              │ (conflated: partially both)      │
              └─────────────────────────────────┘

              Proposed (dual identity)
              ┌──────────────────────────────────────────────────┐
              │ canonical_id = f(project, text_hash)             │
              │   → Same decision always → same canonical_id    │
              │                                                  │
              │ instance_id = f(conversation_id, local_id)       │
              │   → Each mention in each archive → unique       │
              │                                                  │
              │ instances = [                                    │
              │   {instance_id, conversation_id, local_id, ...} │
              │   {instance_id, conversation_id, local_id, ...} │
              │ ]                                                │
              └──────────────────────────────────────────────────┘
```

### Query patterns enabled

```
"Show me all mentions of this decision"
  → db.find({"canonical_id": X}).instances[]

"What decisions were in this specific archive?"
  → db.find({"instances.conversation_id": conv_uuid})

"Is this a restatement or a new decision?"
  → Compute canonical_id → if exists → restatement (add instance)
  → If not → new decision (or near-match → flag for review)
```

---

## Existing Code Surface

### UUID derivation (vectordb/uuidv8.py)

```python
# Line 251-274: Current decision_id()
def decision_id(project_uuid, decision_text, originated_conversation_id):
    text_hash = hashlib.sha256(decision_text.encode("utf-8")).hexdigest()[:16]
    content = text_hash + str(originated_conversation_id)
    derived = uuid.uuid5(project_uuid, content)
    ts_ms = _extract_timestamp(originated_conversation_id)
    return v8(namespace=derived, timestamp_ms=ts_ms)
```

Problem: `originated_conversation_id` is baked in, so same text from different conversations produces different UUIDs.

```python
# Line 224-248: Current thread_id()
def thread_id(project_uuid, thread_title, first_seen_conversation_id):
    content = thread_title + str(first_seen_conversation_id)
    ...
```

Same problem for threads.

### Decision registry (vectordb/decision_registry.py)

```python
# Line 69-71: UUID derivation
decision_uuid = str(derive_decision_uuid(
    project_uuid, text, originated_conversation_id
))

# Line 171-191: Document schema
doc = {
    "uuid": decision_uuid,         # Single conflated identity
    "local_id": local_id,          # Session-scoped
    "text": text[:8000],
    "text_hash": text_hash,
    "project": project,
    "originated_conversation": str(originated_conversation_id),
    # ... no instances array, no canonical_id
}
```

### Upsert logic (decision_registry.py:27-90)

Three branches:
- `existing.text_hash == text_hash` → validate (same text, same UUID)
- `existing` with different hash → update (same UUID, text changed)
- No existing → insert (new UUID)

This logic needs to change to check by **canonical_id** first, not by the conflated UUID.

### Thread registry (vectordb/thread_registry.py)

Same structure: single `uuid`, no instances array, no canonical_id.

### Sync script (scripts/sync_compression.py:401-417)

Calls `upsert_decision()` with `originated_conversation_id=conversation_id`. This is where the conflation happens -- the archive's conversation becomes part of the UUID.

---

## Files to Modify

### 1. `vectordb/uuidv8.py` (~+20 lines)

Add two new derivation functions:

```python
def canonical_decision_id(project_uuid, decision_text):
    """Derive a canonical ID from project + content only.

    Same decision text in the same project always produces the same ID,
    regardless of which conversation it appeared in.
    """
    text_hash = hashlib.sha256(decision_text.encode("utf-8")).hexdigest()[:16]
    derived = uuid.uuid5(project_uuid, f"canonical:decision:{text_hash}")
    return v8(namespace=derived, timestamp_ms=0)  # timestamp=0 for canonical stability


def instance_decision_id(conversation_id, local_id):
    """Derive an instance ID from conversation + local ID.

    Each mention of a decision in a specific archive gets a unique
    instance ID. "D001 in archive A" != "D001 in archive B".
    """
    content = f"instance:{conversation_id}:{local_id}"
    derived = uuid.uuid5(BASE_UUID, content)
    ts_ms = _extract_timestamp(conversation_id) if isinstance(conversation_id, uuid.UUID) else int(time.time() * 1000)
    return v8(namespace=derived, timestamp_ms=ts_ms)
```

Same pattern for threads:

```python
def canonical_thread_id(project_uuid, thread_title):
    ...

def instance_thread_id(conversation_id, local_id):
    ...
```

### 2. `vectordb/decision_registry.py` (~+40 lines)

**Schema change:** Add `canonical_id`, `instances[]`, keep `uuid` as backward-compat alias for `canonical_id`.

```python
# New document schema
doc = {
    "uuid": canonical_id,           # Backward compat (= canonical_id)
    "canonical_id": canonical_id,   # Content-addressed: f(project, text_hash)
    "instances": [                  # All appearances across archives
        {
            "instance_id": instance_id,
            "conversation_id": str(conversation_id),
            "local_id": local_id,
            "archive_date": now.isoformat(),
            "status": "active",     # "active", "carried_forward", "superseded"
        }
    ],
    "local_id": local_id,           # Latest local_id (for display)
    "text": text[:8000],
    "text_hash": text_hash,
    ...
}
```

**Upsert logic change:**

```python
def upsert_decision(...):
    canonical_id = str(canonical_decision_id(project_uuid, text))
    instance_id = str(instance_decision_id(conversation_id, local_id))

    existing = collection.find_one({"canonical_id": canonical_id})

    if existing is not None and existing.get("text_hash") == text_hash:
        # Same canonical + same hash → add instance, validate
        return _validate_decision(collection, canonical_id, instance_id,
                                  conversation_id, local_id, now, db)

    if existing is not None:
        # Same canonical + different hash → text was revised
        return _update_decision(...)

    # New canonical → check for near-duplicates (semantic)
    return _insert_decision(...)
```

**`_validate_decision` change:** Push new instance into `instances` array via `$addToSet`:

```python
collection.update_one(
    {"canonical_id": canonical_id},
    {
        "$set": {"last_validated": now, "hops_since_validated": 0, ...},
        "$addToSet": {"instances": new_instance_doc},
    },
)
```

### 3. `vectordb/thread_registry.py` (~+30 lines)

Same pattern: add `canonical_id`, `instances[]`, update upsert logic.

### 4. `scripts/sync_compression.py` (~+5 lines)

No major changes needed -- `upsert_decision()` handles the dual-identity internally. But the summary output should report instance counts.

### 5. `scripts/prepare_continuation.py` (~+10 lines)

When displaying decisions, show instance count:

```python
instances = len(d.get("instances", []))
instance_str = f" [{instances} mentions]" if instances > 1 else ""
```

### 6. `vectordb/__init__.py` (~+4 lines)

Export new UUID functions.

---

## Migration Strategy

### Backward compatibility

- Keep `uuid` field as an alias for `canonical_id` (existing queries work unchanged)
- Existing documents without `instances[]` treated as having one implicit instance
- `get_text_with_fallback()` and other read paths don't change (they use `uuid`)

### Backfill script: `scripts/backfill_dual_identity.py` (~80 lines)

```python
for doc in collection.find({"canonical_id": {"$exists": False}}):
    canonical_id = str(canonical_decision_id(project_uuid, doc["text"]))
    instance_id = str(instance_decision_id(
        doc["originated_conversation"], doc["local_id"]
    ))
    instance_doc = {
        "instance_id": instance_id,
        "conversation_id": doc["originated_conversation"],
        "local_id": doc["local_id"],
        "archive_date": doc["created_at"],
        "status": "active",
    }

    # Check if another document already has this canonical_id
    existing_canonical = collection.find_one({"canonical_id": canonical_id, "_id": {"$ne": doc["_id"]}})

    if existing_canonical:
        # Merge: add this instance to the existing canonical document
        collection.update_one(
            {"_id": existing_canonical["_id"]},
            {"$addToSet": {"instances": instance_doc}},
        )
        # Remove the duplicate
        collection.delete_one({"_id": doc["_id"]})
    else:
        # Add canonical_id and instances to existing doc
        collection.update_one(
            {"_id": doc["_id"]},
            {"$set": {
                "canonical_id": canonical_id,
                "instances": [instance_doc],
            }},
        )
```

This also deduplicates -- decisions that were the same text but got different UUIDs (because different conversation_ids) will be merged into one canonical with multiple instances.

---

## Implementation Phases

### Phase A: UUID functions

1. Add `canonical_decision_id()`, `instance_decision_id()` to `uuidv8.py`
2. Add `canonical_thread_id()`, `instance_thread_id()` to `uuidv8.py`

**Depends on:** Nothing

### Phase B: Registry schema + upsert logic

1. Update `decision_registry.py` document schema and upsert logic
2. Update `thread_registry.py` document schema and upsert logic

**Depends on:** Phase A

### Phase C: Display integration

1. Update `prepare_continuation.py` to show instance counts
2. Update API/MCP output to include `canonical_id` and instance info

**Depends on:** Phase B

### Phase D: Migration backfill

1. Create `scripts/backfill_dual_identity.py`
2. Run backfill (merges duplicates, adds canonical_id + instances)

**Depends on:** Phase B

```
Phase A ── Phase B ──┬── Phase C
                     └── Phase D
```

---

## Key Design Decisions

### `canonical_id` uses `timestamp_ms=0`

Canonical IDs must be stable regardless of when the decision was first seen. Using `timestamp_ms=0` means the same decision text in the same project always produces the exact same canonical UUID, even if discovered years apart.

### `uuid` aliased to `canonical_id`

Every existing query that uses `uuid` continues to work. New code should use `canonical_id` explicitly.

### Instance deduplication via `$addToSet`

MongoDB's `$addToSet` prevents duplicate instances. If `sync_compression.py` is run twice on the same archive, the instance won't be added twice.

### Merge-on-backfill

During migration, decisions with identical text that got different UUIDs (from different conversations) are merged into one canonical document. The "losing" documents are deleted, their instances added to the winner.

---

## Verification

```bash
# Phase A: UUID functions
python -c "
from vectordb.uuidv8 import canonical_decision_id, instance_decision_id
import uuid

project = uuid.uuid5(uuid.UUID('6ba7b810-9dad-11d1-80b4-00c04fd430c8'), 'forgeos.local')

# Same text → same canonical
c1 = canonical_decision_id(project, 'Use PostgreSQL for storage')
c2 = canonical_decision_id(project, 'Use PostgreSQL for storage')
assert c1 == c2, 'Canonical IDs should match for same text'

# Different text → different canonical
c3 = canonical_decision_id(project, 'Use MongoDB for storage')
assert c1 != c3, 'Different text should produce different canonical'

# Different conversations → different instances
i1 = instance_decision_id(uuid.uuid4(), 'D001')
i2 = instance_decision_id(uuid.uuid4(), 'D001')
assert i1 != i2, 'Same local_id in different convs should differ'
print('All assertions passed')
"

# Phase D: Backfill
python scripts/backfill_dual_identity.py --project "Forge OS" --dry-run
python scripts/backfill_dual_identity.py --project "Forge OS"
```

---

## File Size Estimates

| File | Lines | Action |
|------|-------|--------|
| `vectordb/uuidv8.py` | +20 | Modify |
| `vectordb/decision_registry.py` | +40 | Modify |
| `vectordb/thread_registry.py` | +30 | Modify |
| `vectordb/__init__.py` | +4 | Modify |
| `scripts/prepare_continuation.py` | +10 | Modify |
| `scripts/sync_compression.py` | +5 | Modify |
| `scripts/backfill_dual_identity.py` | ~80 | Create |
| **Total** | **~190** | |
