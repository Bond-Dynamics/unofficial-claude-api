# Content-Addressed Blob Store — Implementation Plan

## Context & Motivation

Forge OS stores all text content inline in MongoDB — decision text (8,000 chars), priming blocks (16,000 chars), thread titles, flag descriptions, conversation summaries, and more. This creates coupling: artifacts can't be versioned, shared, or backed up independently.

**Solution:** A content-addressed blob store (SHA-256) that decouples content from metadata. MongoDB keeps truncated thumbnails for quick display. Full content lives in blobs (local filesystem or GCS).

**Key principle:** Backward compatible. Documents with inline text and no `blob_ref` work unchanged.

## Architecture

```
MongoDB: { text: "truncated...", text_blob_ref: "sha256:a1b2c3..." }
                                         │
                              ┌──────────▼──────────┐
                              │  vectordb/blob_store │
                              │  store() / resolve() │
                              └──────┬───────┬──────┘
                            Local    │       │   GCS
                         data/blobs/ │       │  gs://bucket/
```

## Files Created

| File | Lines | Purpose |
|------|-------|---------|
| `vectordb/blob_store.py` | ~340 | Core module: store, resolve, batch, fallback, backends |
| `scripts/migrate_to_blobs.py` | ~190 | Migration script with dry-run support |

## Files Modified

| File | Changes |
|------|---------|
| `vectordb/config.py` | +5 lines: BLOB_STORE_BACKEND, LOCAL_PATH, GCS_BUCKET, ENABLED |
| `vectordb/__init__.py` | +15 lines: blob store exports |
| `vectordb/decision_registry.py` | +12 lines: text_blob_ref, rationale_blob_ref on insert/update |
| `vectordb/thread_registry.py` | +12 lines: title_blob_ref, resolution_blob_ref |
| `vectordb/priming_registry.py` | +8 lines: content_blob_ref |
| `vectordb/expedition_flags.py` | +8 lines: description_blob_ref, context_blob_ref |
| `vectordb/patterns.py` | +6 lines: content_blob_ref |
| `vectordb/archive.py` | +6 lines: content_summary_blob_ref |
| `vectordb/pipeline.py` | +14 lines: content_blob_ref, summary_blob_ref |
| `vectordb/entanglement.py` | +10 lines: clusters/bridges/loose_ends blob refs |
| `vectordb/attention.py` | +12 lines: get_text_with_fallback in _search_collection |
| `vectordb/gravity.py` | +4 lines: get_text_with_fallback in convergence detection |
| `vectordb/conflicts.py` | +6 lines: get_text_with_fallback in similarity/entity detection |
| `scripts/mcp_server.py` | +15 lines: forge_blob_stats tool |
| `scripts/api_server.py` | +10 lines: GET /api/forge/blob-stats endpoint |

## Key Design Decisions

1. **Per-field blob refs** — `text_blob_ref`, `rationale_blob_ref` etc. (not a single generic ref)
2. **Thumbnails via existing truncation** — MongoDB keeps `text[:8000]` for display
3. **Ref format: `sha256:{64-char-hex}`** — self-describing, collision-resistant
4. **Atomic local writes** — tempfile + os.rename (POSIX atomic)
5. **BLOB_STORE_ENABLED kill switch** — set to `false` for zero-risk rollback
6. **GCS lazy import** — zero cloud deps in local mode

## Verification

```bash
python -c "from vectordb.blob_store import store, resolve; ref = store('test'); print(resolve(ref))"
python scripts/migrate_to_blobs.py --dry-run --stats
curl http://localhost:8000/api/forge/blob-stats
```

## Status: IMPLEMENTED
