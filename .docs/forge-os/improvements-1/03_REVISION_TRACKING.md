# Improvement 3: Bidirectional Revision Tracking

## Priority: 3
## Effort: Low
## Value: Medium

---

## Context & Motivation

The archive (exchange_006) describes a revision chain where decisions evolve:

```
D001 "Use PostgreSQL" (Feb 1)
  └── superseded by D003 "Use MongoDB" (Feb 8)
        └── superseded by D007 "Use PostgreSQL with JSONB" (Feb 15)
```

Currently, `supersede_decision()` in `decision_registry.py:302-339` sets `superseded_by` on the old decision but does NOT set a reciprocal `supersedes` field on the replacement. The relationships are one-directional:

- You can ask "what replaced D001?" -> `D001.superseded_by` = D003's UUID
- You CANNOT ask "what did D003 replace?" without a reverse query
- Dependencies (`dependents`/`dependencies`) are also not reciprocally maintained

---

## Existing Code Surface

### `supersede_decision()` (decision_registry.py:302-339)

```python
def supersede_decision(decision_uuid, superseded_by_uuid, db=None):
    collection.update_one(
        {"uuid": decision_uuid},
        {"$set": {
            "status": "superseded",
            "superseded_by": superseded_by_uuid,  # Only one direction
            "updated_at": now.isoformat(),
        }}
    )
    # No update to the superseding decision
```

### Document schema (decision_registry.py:171-191)

```python
doc = {
    ...
    "dependents": dependents or [],        # UUIDs that depend on this
    "dependencies": dependencies or [],     # local_ids this depends on
    "conflicts_with": [],
    "superseded_by": None,                 # UUID of replacement (one-way)
    # Missing: "supersedes": None
    ...
}
```

### Conflict registration (conflicts.py:179-200)

`register_conflict()` already does bidirectional updates (both A and B get the conflict). This is the pattern to follow.

---

## Files to Modify

### 1. `vectordb/decision_registry.py` (~+25 lines)

#### a. Add `supersedes` field to document schema

In `_insert_decision()` (line ~171), add to doc:

```python
"supersedes": None,  # UUID of the decision this one replaced
```

#### b. Make `supersede_decision()` bidirectional

```python
def supersede_decision(decision_uuid, superseded_by_uuid, db=None):
    if db is None:
        db = get_database()

    collection = db[COLLECTION_DECISION_REGISTRY]
    now = datetime.now(timezone.utc)

    # Mark old decision as superseded
    collection.update_one(
        {"uuid": decision_uuid},
        {"$set": {
            "status": "superseded",
            "superseded_by": superseded_by_uuid,
            "updated_at": now.isoformat(),
        }}
    )

    # Mark new decision as superseding the old one
    collection.update_one(
        {"uuid": superseded_by_uuid},
        {"$set": {
            "supersedes": decision_uuid,
            "updated_at": now.isoformat(),
        }}
    )

    emit_event(...)

    return {"action": "superseded", "uuid": decision_uuid}
```

#### c. Add `get_revision_chain()` function

```python
def get_revision_chain(decision_uuid, db=None):
    """Walk the supersession chain in both directions.

    Returns:
        Dict with 'ancestors' (older versions, root-first),
        'current' (this decision), 'descendants' (newer versions).
    """
    if db is None:
        db = get_database()

    collection = db[COLLECTION_DECISION_REGISTRY]

    # Walk backward via 'supersedes'
    ancestors = []
    current_uuid = decision_uuid
    for _ in range(20):  # Safety limit
        doc = collection.find_one(
            {"uuid": current_uuid},
            {"_id": 0, "embedding": 0},
        )
        if not doc or not doc.get("supersedes"):
            break
        ancestors.append(doc["supersedes"])
        current_uuid = doc["supersedes"]

    # Walk forward via 'superseded_by'
    descendants = []
    current_uuid = decision_uuid
    for _ in range(20):
        doc = collection.find_one(
            {"uuid": current_uuid},
            {"_id": 0, "embedding": 0},
        )
        if not doc or not doc.get("superseded_by"):
            break
        descendants.append(doc["superseded_by"])
        current_uuid = doc["superseded_by"]

    return {
        "ancestors": list(reversed(ancestors)),
        "current": decision_uuid,
        "descendants": descendants,
    }
```

#### d. Add reciprocal dependency linking

```python
def link_dependency(decision_uuid, depends_on_uuid, db=None):
    """Create a bidirectional dependency link.

    decision_uuid depends on depends_on_uuid.
    """
    if db is None:
        db = get_database()

    collection = db[COLLECTION_DECISION_REGISTRY]

    # Add depends_on_uuid to this decision's dependencies
    collection.update_one(
        {"uuid": decision_uuid},
        {"$addToSet": {"dependencies": depends_on_uuid}},
    )

    # Add decision_uuid to the target's dependents
    collection.update_one(
        {"uuid": depends_on_uuid},
        {"$addToSet": {"dependents": decision_uuid}},
    )
```

### 2. `scripts/prepare_continuation.py` (~+10 lines)

Show revision context when a decision has `supersedes`:

```python
if d.get("supersedes"):
    sections.append(f"  (supersedes: {d['supersedes'][:8]}...)")
```

### 3. `vectordb/__init__.py` (~+2 lines)

Export `get_revision_chain`, `link_dependency`.

### 4. `scripts/api_server.py` (~+15 lines)

Add `GET /api/forge/decisions/{uuid}/revisions` endpoint:

```python
@app.get("/api/forge/decisions/{uuid}/revisions")
def get_decision_revisions(uuid: str):
    chain = get_revision_chain(uuid)
    return {"success": True, "data": chain}
```

---

## Migration

### Backfill `supersedes` field

Simple script that walks all documents with `superseded_by` set and writes the reciprocal:

```python
for doc in collection.find({"superseded_by": {"$ne": None}}):
    collection.update_one(
        {"uuid": doc["superseded_by"]},
        {"$set": {"supersedes": doc["uuid"]}},
    )
```

For documents without `supersedes` field at all:

```python
collection.update_many(
    {"supersedes": {"$exists": False}},
    {"$set": {"supersedes": None}},
)
```

This can be added to the dual-identity backfill script or run standalone.

---

## Implementation Phases

### Phase A: Schema + bidirectional supersession

1. Add `supersedes` field to `_insert_decision()` schema
2. Update `supersede_decision()` to write both directions
3. Add `get_revision_chain()` function
4. Add `link_dependency()` function

**Depends on:** Nothing (can run before or after Improvements 1-2)

### Phase B: Display + API

1. Update `prepare_continuation.py` to show revision context
2. Add `/api/forge/decisions/{uuid}/revisions` endpoint

**Depends on:** Phase A

### Phase C: Backfill

1. Backfill `supersedes` field from existing `superseded_by` data
2. Add `supersedes: None` to documents missing the field

**Depends on:** Phase A

```
Phase A ──┬── Phase B
           └── Phase C
```

---

## Key Design Decisions

### Follow the `register_conflict()` pattern

`conflicts.py:179-200` already does bidirectional `$addToSet`. `supersede_decision()` should follow the same pattern for consistency.

### `dependencies` field type change

Currently `dependencies` stores local_ids (strings like "D001"). For bidirectional linking, `link_dependency()` uses UUIDs. Both formats should coexist during migration -- `dependencies` keeps local_ids for archive display, a new `depends_on_uuids` field stores resolved UUIDs.

### Revision chain depth limit

`get_revision_chain()` caps at 20 hops in each direction. This prevents runaway traversal on corrupted data. In practice, revision chains are unlikely to exceed 5-10 levels.

---

## Verification

```bash
python -c "
from vectordb.decision_registry import supersede_decision, get_revision_chain
from vectordb.db import get_database

db = get_database()
col = db['decision_registry']

# Check a superseded decision
doc = col.find_one({'status': 'superseded'})
if doc:
    print(f'Superseded: {doc[\"uuid\"][:8]}')
    print(f'  superseded_by: {doc.get(\"superseded_by\", \"N/A\")}')
    chain = get_revision_chain(doc['uuid'])
    print(f'  Chain: {len(chain[\"ancestors\"])} ancestors, {len(chain[\"descendants\"])} descendants')
else:
    print('No superseded decisions found')
"
```

---

## File Size Estimates

| File | Lines | Action |
|------|-------|--------|
| `vectordb/decision_registry.py` | +25 | Modify (supersede, chain, link) |
| `scripts/prepare_continuation.py` | +10 | Modify |
| `vectordb/__init__.py` | +2 | Modify |
| `scripts/api_server.py` | +15 | Modify |
| **Total** | **~52** | |
