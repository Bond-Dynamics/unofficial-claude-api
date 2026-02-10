# Improvement 5: Blob Store Integration with Sync Pipeline

## Priority: 5
## Effort: Low
## Value: Low-Medium

---

## Context & Motivation

The content-addressed blob store (`vectordb/blob_store.py`) was just implemented and integrated with registries and read paths. However, the sync pipeline scripts do not yet use it for storing archive content itself. Archives are the raw input to the entire graph -- storing them as blobs provides:

1. **Archive deduplication**: Re-syncing the same archive is a no-op (same content = same hash = same blob)
2. **Integrity verification**: The blob's SHA-256 ref can replace/supplement the compression_registry checksum
3. **Full-text retrieval**: Any archive can be retrieved later by ref without keeping the original file
4. **Lineage provenance**: Lineage edges can reference the exact archive blob that created them

The compression_registry already stores a `checksum` field (SHA-256 of archive content). The blob store uses the same SHA-256 algorithm. Storing the archive as a blob makes the checksum AND the content available in one operation.

---

## Existing Code Surface

### Archive ingestion (sync_compression.py:347-510)

```python
def sync_archive(parsed, ..., archive_text=None, ...):
    ...
    # Line 482: Checksum computed from archive_text
    checksum = compute_checksum(archive_text) if archive_text else None
    # Line 484-494: Compression registered with checksum
    register_compression(
        ...,
        archive_checksum=checksum,
        ...
    )
```

`archive_text` is available as a parameter but only used for checksumming.

### Compression registry (vectordb/compression_registry.py:57-70)

```python
doc = {
    "compression_tag": compression_tag,
    ...
    "checksum": archive_checksum or "",   # SHA-256 hex digest
    # Missing: archive_blob_ref
    ...
}
```

### Blob store API (vectordb/blob_store.py)

```python
store(content) -> "sha256:{hash}" or None   # Returns ref
resolve(blob_ref) -> str                     # Returns full content
exists(blob_ref) -> bool
```

The blob store `store()` computes SHA-256 and returns a ref in `sha256:{hash}` format. The compression_registry's `checksum` field stores a bare SHA-256 hex digest. These are the same hash, just formatted differently (`sha256:abc...` vs `abc...`).

### Lineage edges (vectordb/lineage.py:61-76)

```python
doc = {
    "edge_uuid": edge_uuid,
    "source_conversation": source_conversation,
    "target_conversation": target_conversation,
    "compression_tag": compression_tag or "",
    # Missing: archive_blob_ref
    ...
}
```

---

## Files to Modify

### 1. `scripts/sync_compression.py` (~+10 lines)

In `sync_archive()`, after parsing but before syncing entities:

```python
from vectordb.blob_store import store as blob_store

def sync_archive(parsed, ..., archive_text=None, ...):
    ...
    # Store archive as blob
    archive_blob_ref = None
    if archive_text:
        archive_blob_ref = blob_store(archive_text, collection_hint="archives")

    ...

    # Pass blob_ref to compression registration
    if compression_tag and not dry_run:
        register_compression(
            ...,
            archive_checksum=checksum,
            archive_blob_ref=archive_blob_ref,  # NEW
            ...
        )

    # Include in lineage edge
    if source_conversation_id and not dry_run:
        edge_result = add_edge(
            ...,
            archive_blob_ref=archive_blob_ref,  # NEW
            ...
        )

    summary["archive_blob_ref"] = archive_blob_ref
    ...
```

### 2. `vectordb/compression_registry.py` (~+8 lines)

Add `archive_blob_ref` parameter to `register_compression()`:

```python
def register_compression(
    ...,
    archive_blob_ref=None,  # NEW
    ...
):
    ...
    if existing is None:
        doc = {
            ...
            "archive_blob_ref": archive_blob_ref or "",  # NEW
            ...
        }
    else:
        if archive_blob_ref and not existing.get("archive_blob_ref"):
            update["$set"]["archive_blob_ref"] = archive_blob_ref
```

Add retrieval function:

```python
def get_archive_content(compression_tag, db=None):
    """Retrieve the full archive content for a compression event.

    Uses blob_ref if available, returns None otherwise.
    """
    record = get_compression(compression_tag, db=db)
    if not record:
        return None

    blob_ref = record.get("archive_blob_ref")
    if not blob_ref:
        return None

    from vectordb.blob_store import resolve
    try:
        return resolve(blob_ref)
    except Exception:
        return None
```

### 3. `vectordb/lineage.py` (~+5 lines)

Add `archive_blob_ref` parameter to `add_edge()`:

```python
def add_edge(
    ...,
    archive_blob_ref=None,  # NEW
    ...
):
    ...
    if existing is None:
        doc = {
            ...
            "archive_blob_ref": archive_blob_ref or "",  # NEW
            ...
        }
    else:
        if archive_blob_ref and not existing.get("archive_blob_ref"):
            update.setdefault("$set", {})["archive_blob_ref"] = archive_blob_ref
```

### 4. `scripts/api_server.py` (~+15 lines)

Add endpoint to retrieve archive content by compression tag:

```python
@app.get("/api/forge/compressions/{tag}/archive")
def get_compression_archive(tag: str):
    from vectordb.compression_registry import get_archive_content
    content = get_archive_content(tag)
    if content is None:
        return {"success": False, "error": "Archive not found or no blob stored"}
    return {"success": True, "data": {"content": content}}
```

### 5. `scripts/mcp_server.py` (~+15 lines)

Add `forge_get_archive` MCP tool:

```python
@mcp.tool()
def forge_get_archive(compression_tag: str) -> str:
    """Retrieve the full archive content for a compression event."""
    from vectordb.compression_registry import get_archive_content
    content = get_archive_content(compression_tag)
    if content is None:
        return "Archive not found or no blob stored for this compression tag."
    return content[:8000]  # Truncate for context window safety
```

---

## Implementation Phases

### Phase A: Sync pipeline integration

1. Store archive as blob in `sync_archive()`
2. Pass `archive_blob_ref` to `register_compression()`
3. Pass `archive_blob_ref` to `add_edge()`

**Depends on:** Blob store (already implemented)

### Phase B: Registry + lineage schema

1. Add `archive_blob_ref` parameter and field to `register_compression()`
2. Add `archive_blob_ref` parameter and field to `add_edge()`
3. Add `get_archive_content()` to `compression_registry.py`

**Depends on:** Nothing (schema additions are backward compatible)

### Phase C: API/MCP endpoints

1. Add `GET /api/forge/compressions/{tag}/archive` endpoint
2. Add `forge_get_archive` MCP tool

**Depends on:** Phases A + B

```
Phase A ──┐
Phase B ──┴── Phase C
```

---

## Key Design Decisions

### Blob ref replaces checksum for verification

The blob store's ref IS a checksum (`sha256:{hash}`). Storing both `checksum` and `archive_blob_ref` is redundant but harmless. The `archive_blob_ref` is strictly more useful since it enables content retrieval, not just verification. Existing `verify_checksum()` continues to work unchanged.

### No migration needed for existing compressions

Old compression records without `archive_blob_ref` simply return `None` from `get_archive_content()`. Re-syncing an old archive will populate the blob ref going forward. No backfill required.

### Truncation on MCP retrieval

Archives can be very large (10,000+ tokens). The MCP tool truncates to 8,000 chars to avoid blowing up the context window. The API endpoint returns full content.

---

## Verification

```bash
# Phase A+B: Sync with blob storage
python scripts/sync_compression.py \
    --project "Forge OS" \
    --project-uuid "..." \
    --file data/artifacts/.../test_archive.md

# Check blob ref was stored
python -c "
from vectordb.compression_registry import get_compression, get_archive_content

comp = get_compression('test-tag')
print(f'Blob ref: {comp.get(\"archive_blob_ref\", \"N/A\")}')

content = get_archive_content('test-tag')
if content:
    print(f'Archive retrieved: {len(content)} chars')
else:
    print('No archive blob found')
"

# Phase C: API endpoint
curl http://localhost:8000/api/forge/compressions/test-tag/archive | python -m json.tool
```

---

## File Size Estimates

| File | Lines | Action |
|------|-------|--------|
| `scripts/sync_compression.py` | +10 | Modify |
| `vectordb/compression_registry.py` | +8 | Modify (param + get_archive_content) |
| `vectordb/lineage.py` | +5 | Modify |
| `scripts/api_server.py` | +15 | Modify |
| `scripts/mcp_server.py` | +15 | Modify |
| **Total** | **~53** | |
