"""Vector search for Claude conversations using MongoDB Atlas and VoyageAI.

Forge OS Layer 1: MEMORY — 15-function memory system with typed content,
pattern learning, execution context, scratchpad, and archival.
"""

from vectordb.archive import archive_retrieve, archive_store, forget
from vectordb.context import context_flush, context_load, context_resize
from vectordb.events import emit_event
from vectordb.patterns import pattern_match, pattern_store
from vectordb.scratchpad import (
    scratchpad_clear,
    scratchpad_delete,
    scratchpad_get,
    scratchpad_list,
    scratchpad_set,
)
from vectordb.vector_store import vector_search, vector_store

__all__ = [
    # Vector store
    "vector_store",
    "vector_search",
    # Patterns
    "pattern_store",
    "pattern_match",
    # Context
    "context_load",
    "context_flush",
    "context_resize",
    # Scratchpad
    "scratchpad_get",
    "scratchpad_set",
    "scratchpad_delete",
    "scratchpad_clear",
    "scratchpad_list",
    # Archive
    "archive_store",
    "archive_retrieve",
    "forget",
    # Events
    "emit_event",
]
