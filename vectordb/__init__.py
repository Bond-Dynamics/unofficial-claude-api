"""Vector search for Claude conversations using MongoDB Atlas and VoyageAI.

Forge OS Layer 1: MEMORY — 15-function memory system with typed content,
pattern learning, execution context, scratchpad, and archival.

Forge OS Layer 2: GRAPH — UUIDv8 deterministic identity for conversations,
threads, decisions, and lineage edges. Thread/decision registries,
conflict detection, and lineage tracking across compression hops.
"""

from vectordb.attention import (
    alerts as attention_alerts,
    compute_attention,
    context_load as attention_context_load,
    enrich_with_entanglement,
    project_context as attention_project_context,
    recall as attention_recall,
)
from vectordb.archive import archive_retrieve, archive_store, forget
from vectordb.compression_registry import (
    compute_checksum,
    get_compression,
    list_compressions,
    register_compression,
    verify_checksum,
)
from vectordb.conflicts import detect_conflicts, register_conflict
from vectordb.entanglement import (
    ensure_thread_embeddings,
    get_latest_scan as get_latest_entanglement_scan,
    get_scan as get_entanglement_scan,
    list_scans as list_entanglement_scans,
    scan as scan_entanglement,
    scan_and_save as scan_entanglement_and_save,
    scan_project as scan_entanglement_project,
    scan_project_and_save as scan_entanglement_project_and_save,
)
from vectordb.conversation_registry import (
    get_conversation,
    get_conversation_by_uuid,
    list_project_conversations,
    list_projects,
    register_conversation,
    resolve_id,
)
from vectordb.context import context_flush, context_load, context_resize
from vectordb.expedition_flags import (
    delete_flag,
    get_all_flags,
    get_flags_by_category,
    get_pending_flags,
    mark_flag_compiled,
    plant_flag,
)
from vectordb.decision_registry import (
    find_similar_decisions,
    get_active_decisions,
    get_stale_decisions,
    increment_decision_hops,
    supersede_decision,
    upsert_decision,
)
from vectordb.events import emit_event
from vectordb.lineage import (
    add_edge,
    get_ancestors,
    get_descendants,
    get_full_graph,
    get_lineage_chain,
    trace_conversation,
)
from vectordb.patterns import pattern_match, pattern_store
from vectordb.priming_registry import (
    deactivate_priming_block,
    find_relevant_priming,
    get_priming_block,
    list_priming_blocks,
    upsert_priming_block,
)
from vectordb.scratchpad import (
    scratchpad_clear,
    scratchpad_delete,
    scratchpad_get,
    scratchpad_list,
    scratchpad_set,
)
from vectordb.thread_registry import (
    get_active_threads,
    get_stale_threads,
    increment_thread_hops,
    resolve_thread,
    upsert_thread,
)
from vectordb.uuidv8 import (
    BASE_UUID,
    composite_pair,
    compression_tag_id,
    conversation_id,
    decision_id,
    lineage_id,
    parent_child,
    project_id,
    thread_id,
    v5,
    v8,
    v8_from_string,
)
from vectordb.claude_api import (
    ClaudeAPIError,
    ClaudeSession,
    get_session,
    reset_session,
)
from vectordb.gravity import orchestrate as gravity_orchestrate
from vectordb.project_roles import (
    assign_role,
    delete_lens,
    get_lens,
    get_role,
    list_lenses,
    list_roles,
    remove_role,
    save_lens,
)
from vectordb.sync_manifest import (
    load_manifest,
    resolve_all_targets,
    validate_manifest,
)
from vectordb.sync_engine import sync_all, sync_one
from vectordb.blob_store import (
    BlobNotFoundError,
    blob_stats,
    get_text_with_fallback,
    resolve_documents,
    store as blob_store_store,
    resolve as blob_resolve,
    resolve_batch as blob_resolve_batch,
)
from vectordb.vector_store import vector_search, vector_store

__all__ = [
    # Attention engine
    "attention_recall",
    "compute_attention",
    "attention_project_context",
    "attention_context_load",
    "enrich_with_entanglement",
    "attention_alerts",
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
    # UUIDv8 identity system
    "BASE_UUID",
    "v5",
    "v8",
    "v8_from_string",
    "composite_pair",
    "parent_child",
    "project_id",
    "conversation_id",
    "thread_id",
    "decision_id",
    "lineage_id",
    "compression_tag_id",
    # Thread registry
    "upsert_thread",
    "get_active_threads",
    "resolve_thread",
    "get_stale_threads",
    "increment_thread_hops",
    # Decision registry
    "upsert_decision",
    "get_active_decisions",
    "get_stale_decisions",
    "supersede_decision",
    "increment_decision_hops",
    "find_similar_decisions",
    # Conflicts
    "detect_conflicts",
    "register_conflict",
    # Conversation registry
    "register_conversation",
    "get_conversation",
    "get_conversation_by_uuid",
    "list_project_conversations",
    "list_projects",
    "resolve_id",
    # Lineage
    "add_edge",
    "get_ancestors",
    "get_descendants",
    "get_full_graph",
    "get_lineage_chain",
    "trace_conversation",
    # Compression registry
    "register_compression",
    "get_compression",
    "list_compressions",
    "verify_checksum",
    "compute_checksum",
    # Priming registry
    "upsert_priming_block",
    "get_priming_block",
    "find_relevant_priming",
    "list_priming_blocks",
    "deactivate_priming_block",
    # Expedition flags
    "plant_flag",
    "get_pending_flags",
    "get_flags_by_category",
    "mark_flag_compiled",
    "delete_flag",
    "get_all_flags",
    # Entanglement discovery
    "ensure_thread_embeddings",
    "scan_entanglement",
    "scan_entanglement_and_save",
    "scan_entanglement_project",
    "scan_entanglement_project_and_save",
    "get_latest_entanglement_scan",
    "get_entanglement_scan",
    "list_entanglement_scans",
    # Claude.ai API client
    "ClaudeSession",
    "ClaudeAPIError",
    "get_session",
    "reset_session",
    # Sync manifest
    "load_manifest",
    "resolve_all_targets",
    "validate_manifest",
    "sync_all",
    "sync_one",
    # Blob store (content-addressed storage)
    "BlobNotFoundError",
    "blob_stats",
    "blob_store_store",
    "blob_resolve",
    "blob_resolve_batch",
    "get_text_with_fallback",
    "resolve_documents",
    # Gravity assist (Layer 3.5)
    "gravity_orchestrate",
    "assign_role",
    "get_role",
    "list_roles",
    "remove_role",
    "save_lens",
    "get_lens",
    "list_lenses",
    "delete_lens",
]
