"""Forge OS: Content-addressed blob store.

Decouples large text content from MongoDB metadata. Documents keep
truncated thumbnails for display; full text lives in blobs retrievable
by SHA-256 hash.

Backward compatible: documents with inline text and no blob_ref
continue to work unchanged via get_text_with_fallback().

Backends:
  - local: Git-like sharded filesystem (data/blobs/a1/b2/a1b2c3...)
  - gcs:   Google Cloud Storage (lazy import, zero deps when unused)
"""

import hashlib
import json
import os
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from vectordb.config import (
    BLOB_STORE_BACKEND,
    BLOB_STORE_ENABLED,
    BLOB_STORE_GCS_BUCKET,
    BLOB_STORE_LOCAL_PATH,
)


class BlobNotFoundError(Exception):
    """Raised when a blob ref cannot be resolved."""


# ---------------------------------------------------------------------------
# Hash computation
# ---------------------------------------------------------------------------

def _compute_hash(content):
    """SHA-256 of UTF-8 encoded content. Returns full 64-char hex string."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _parse_ref(blob_ref):
    """Extract the hex hash from a 'sha256:{hash}' ref string.

    Validates format: sha256:{64-digit hex}.
    """
    if not blob_ref or not isinstance(blob_ref, str):
        raise BlobNotFoundError(f"Invalid blob ref: {blob_ref}")
    if not blob_ref.startswith("sha256:"):
        raise BlobNotFoundError(f"Invalid blob ref format: {blob_ref}")
    hex_hash = blob_ref[7:]
    if len(hex_hash) != 64:
        raise BlobNotFoundError(f"Invalid hash length: {len(hex_hash)}")
    try:
        int(hex_hash, 16)
    except ValueError:
        raise BlobNotFoundError(f"Invalid hex in blob ref: {hex_hash}")
    return hex_hash


def _shard_path(hex_hash):
    """Return (shard_dir, filename) for git-like 2-level sharding."""
    return hex_hash[:2], hex_hash[2:4], hex_hash


# ---------------------------------------------------------------------------
# Local filesystem backend
# ---------------------------------------------------------------------------

class _LocalBackend:
    """Git-like sharded filesystem storage.

    Path: {base}/{a1}/{b2}/{full_hash}
    Atomic writes via tempfile + os.rename.
    """

    def __init__(self, base_path):
        self._base = Path(base_path)

    def store(self, hex_hash, content):
        shard1, shard2, filename = _shard_path(hex_hash)
        target_dir = self._base / shard1 / shard2
        target_path = target_dir / filename

        if target_path.exists():
            return  # idempotent

        target_dir.mkdir(parents=True, exist_ok=True)

        fd, tmp_path = tempfile.mkstemp(dir=str(target_dir))
        closed = False
        try:
            os.write(fd, content.encode("utf-8"))
            os.close(fd)
            closed = True
            os.rename(tmp_path, str(target_path))
        except Exception:
            if not closed:
                try:
                    os.close(fd)
                except OSError:
                    pass
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
            raise

    def resolve(self, hex_hash):
        shard1, shard2, filename = _shard_path(hex_hash)
        target_path = self._base / shard1 / shard2 / filename

        if not target_path.exists():
            raise BlobNotFoundError(f"Blob not found: sha256:{hex_hash}")

        return target_path.read_text(encoding="utf-8")

    def resolve_batch(self, hex_hashes):
        results = {}

        def _read_one(h):
            try:
                return h, self.resolve(h)
            except BlobNotFoundError:
                return h, None

        with ThreadPoolExecutor(max_workers=8) as executor:
            futures = [executor.submit(_read_one, h) for h in hex_hashes]
            for future in as_completed(futures):
                h, content = future.result()
                if content is not None:
                    results[f"sha256:{h}"] = content

        return results

    def exists(self, hex_hash):
        shard1, shard2, filename = _shard_path(hex_hash)
        return (self._base / shard1 / shard2 / filename).exists()

    def delete(self, hex_hash):
        shard1, shard2, filename = _shard_path(hex_hash)
        target_path = self._base / shard1 / shard2 / filename
        if target_path.exists():
            target_path.unlink()
            return True
        return False

    def stats(self):
        blob_count = 0
        total_bytes = 0
        for path in self._base.rglob("*"):
            if path.is_file():
                blob_count += 1
                total_bytes += path.stat().st_size
        return {
            "backend": "local",
            "path": str(self._base),
            "blob_count": blob_count,
            "total_bytes": total_bytes,
        }


# ---------------------------------------------------------------------------
# GCS backend
# ---------------------------------------------------------------------------

class _GCSBackend:
    """Google Cloud Storage backend.

    Key: blobs/{a1}/{b2}/{full_hash}
    Lazy-imports google.cloud.storage.
    """

    def __init__(self, bucket_name):
        from google.cloud import storage
        self._client = storage.Client()
        self._bucket = self._client.bucket(bucket_name)
        self._bucket_name = bucket_name

    def _key(self, hex_hash):
        shard1, shard2, filename = _shard_path(hex_hash)
        return f"blobs/{shard1}/{shard2}/{filename}"

    def store(self, hex_hash, content):
        key = self._key(hex_hash)
        blob = self._bucket.blob(key)
        if blob.exists():
            return  # idempotent
        blob.upload_from_string(content.encode("utf-8"), content_type="text/plain")

    def resolve(self, hex_hash):
        key = self._key(hex_hash)
        blob = self._bucket.blob(key)
        if not blob.exists():
            raise BlobNotFoundError(f"Blob not found in GCS: sha256:{hex_hash}")
        return blob.download_as_text(encoding="utf-8")

    def resolve_batch(self, hex_hashes):
        results = {}

        def _read_one(h):
            try:
                return h, self.resolve(h)
            except BlobNotFoundError:
                return h, None

        with ThreadPoolExecutor(max_workers=8) as executor:
            futures = [executor.submit(_read_one, h) for h in hex_hashes]
            for future in as_completed(futures):
                h, content = future.result()
                if content is not None:
                    results[f"sha256:{h}"] = content

        return results

    def exists(self, hex_hash):
        return self._bucket.blob(self._key(hex_hash)).exists()

    def delete(self, hex_hash):
        blob = self._bucket.blob(self._key(hex_hash))
        if blob.exists():
            blob.delete()
            return True
        return False

    def stats(self):
        blob_count = 0
        total_bytes = 0
        for blob in self._bucket.list_blobs(prefix="blobs/"):
            blob_count += 1
            total_bytes += blob.size or 0
        return {
            "backend": "gcs",
            "bucket": self._bucket_name,
            "blob_count": blob_count,
            "total_bytes": total_bytes,
        }


# ---------------------------------------------------------------------------
# Backend singleton
# ---------------------------------------------------------------------------

_backend_instance = None
_backend_lock = threading.Lock()


def _get_backend():
    """Singleton backend based on BLOB_STORE_BACKEND config."""
    global _backend_instance
    if _backend_instance is not None:
        return _backend_instance

    with _backend_lock:
        if _backend_instance is not None:
            return _backend_instance

        if BLOB_STORE_BACKEND == "gcs" and BLOB_STORE_GCS_BUCKET:
            _backend_instance = _GCSBackend(BLOB_STORE_GCS_BUCKET)
        else:
            _backend_instance = _LocalBackend(BLOB_STORE_LOCAL_PATH)

    return _backend_instance


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def store(content, collection_hint=None):
    """Hash content (SHA-256), store via backend, return 'sha256:{hash}'.

    Idempotent: same content always returns same ref (deduplication).
    Returns None if blob store is disabled or content is empty/None.
    """
    if not BLOB_STORE_ENABLED or not content:
        return None

    hex_hash = _compute_hash(content)
    _get_backend().store(hex_hash, content)
    return f"sha256:{hex_hash}"


def resolve(blob_ref):
    """Fetch full content by ref. Raises BlobNotFoundError if missing."""
    hex_hash = _parse_ref(blob_ref)
    return _get_backend().resolve(hex_hash)


def resolve_batch(blob_refs):
    """Batch-fetch multiple refs. Returns dict[ref, content].

    Missing refs omitted (no error). Uses ThreadPoolExecutor for parallel I/O.
    """
    if not blob_refs:
        return {}

    hex_hashes = []
    for ref in blob_refs:
        try:
            hex_hashes.append(_parse_ref(ref))
        except BlobNotFoundError:
            continue

    return _get_backend().resolve_batch(hex_hashes)


def exists(blob_ref):
    """Check if blob exists without fetching content."""
    try:
        hex_hash = _parse_ref(blob_ref)
    except BlobNotFoundError:
        return False
    return _get_backend().exists(hex_hash)


def delete(blob_ref):
    """Delete a blob. Returns True if deleted, False if not found."""
    try:
        hex_hash = _parse_ref(blob_ref)
    except BlobNotFoundError:
        return False
    return _get_backend().delete(hex_hash)


def get_text_with_fallback(doc, text_field, ref_field=None):
    """Resolve blob if ref_field present, else return inline text_field.

    This is the key backward-compatibility function.
    Pattern:
      1. If doc has ref_field and blob exists -> return blob content
      2. Else -> return doc[text_field] (existing inline text)
    """
    if ref_field is None:
        ref_field = f"{text_field}_blob_ref"

    blob_ref = doc.get(ref_field)
    if blob_ref:
        try:
            return resolve(blob_ref)
        except BlobNotFoundError:
            pass

    return doc.get(text_field, "")


def resolve_documents(docs, text_field, ref_field=None):
    """Batch-resolve blobs for a list of docs. Modifies docs in place.

    Collects all refs, batch-fetches, updates text_field on each doc.
    Falls back to inline text for docs without refs.
    Returns the modified list.
    """
    if ref_field is None:
        ref_field = f"{text_field}_blob_ref"

    refs_to_resolve = {}
    for i, doc in enumerate(docs):
        blob_ref = doc.get(ref_field)
        if blob_ref:
            refs_to_resolve.setdefault(blob_ref, []).append(i)

    if not refs_to_resolve:
        return docs

    resolved = resolve_batch(list(refs_to_resolve.keys()))

    for ref, indices in refs_to_resolve.items():
        content = resolved.get(ref)
        if content is not None:
            for idx in indices:
                docs[idx][text_field] = content

    return docs


def blob_stats():
    """Return blob store statistics (count, total size, backend type)."""
    return _get_backend().stats()


def _store_if_large(content, threshold=500):
    """Store content as blob only if it exceeds threshold chars.

    Returns (blob_ref_or_None, content_to_store_inline).
    For small content, returns (None, content) — no blob created.
    For large content, returns (ref, truncated_thumbnail).
    """
    if not BLOB_STORE_ENABLED or not content or len(content) <= threshold:
        return None, content

    blob_ref = store(content)
    return blob_ref, content


def store_json(data, collection_hint=None):
    """Store a JSON-serializable object as a blob.

    Useful for entanglement scan results (clusters, bridges, loose_ends)
    that can be very large.
    """
    if not BLOB_STORE_ENABLED or data is None:
        return None

    content = json.dumps(data, default=str, ensure_ascii=False)
    return store(content, collection_hint=collection_hint)


def resolve_json(blob_ref):
    """Resolve a blob ref and parse as JSON."""
    content = resolve(blob_ref)
    return json.loads(content)


def get_json_with_fallback(doc, field, ref_field=None):
    """Resolve JSON blob if ref_field present, else return inline field value."""
    if ref_field is None:
        ref_field = f"{field}_blob_ref"

    blob_ref = doc.get(ref_field)
    if blob_ref:
        try:
            return resolve_json(blob_ref)
        except (BlobNotFoundError, json.JSONDecodeError):
            pass

    return doc.get(field)
