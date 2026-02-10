"""Forge OS MCP Server — Semantic memory tools for LLMs.

Exposes 18 tools via the Model Context Protocol (stdio transport).
All tools return JSON strings. Write tools include action/uuid fields.
Error handling wraps all calls — exceptions never propagate to MCP transport.

Usage:
    claude mcp add forge-os -- python scripts/mcp_server.py
    # Then in Claude Code: call forge_recall, forge_stats, etc.
"""

import json
import os
import sys
import time
from pathlib import Path
from typing import Optional

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from mcp.server.fastmcp import FastMCP

from vectordb.attention import alerts, context_load, project_context, recall
from vectordb.conversation_registry import list_projects, resolve_id
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
from vectordb.db import get_database
from vectordb.entanglement import get_latest_scan
from vectordb.events import emit_event
from vectordb.lineage import trace_conversation
from vectordb.scratchpad import scratchpad_list, scratchpad_set
from vectordb.vector_store import vector_search

mcp = FastMCP("forge-os", description="Forge OS semantic memory for LLMs")

_SESSION_ID = f"forge-mcp-{os.getpid()}-{int(time.time())}"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _serialize(obj):
    """Recursively convert MongoDB-unfriendly types for JSON serialization."""
    from datetime import datetime

    if isinstance(obj, dict):
        return {k: _serialize(v) for k, v in obj.items() if k != "_id"}
    if isinstance(obj, list):
        return [_serialize(item) for item in obj]
    if isinstance(obj, set):
        return sorted(_serialize(item) for item in obj)
    if isinstance(obj, datetime):
        return obj.isoformat()
    return obj


def _json_response(data):
    """Serialize data to a JSON string for MCP tool responses."""
    return json.dumps(_serialize(data), default=str)


# ---------------------------------------------------------------------------
# Tool 1: forge_recall — Attention-weighted cross-collection search
# ---------------------------------------------------------------------------

@mcp.tool()
def forge_recall(
    query: str,
    project: Optional[str] = None,
    budget: Optional[int] = None,
) -> str:
    """Search Forge OS memory with attention-weighted scoring.

    Searches decisions, threads, priming blocks, patterns, conversations,
    and messages. Results are ranked by a multi-signal attention formula
    that weights semantic similarity, epistemic confidence, freshness,
    conflict salience, and category importance.

    Args:
        query: What to search for (natural language).
        project: Optional project name to restrict search.
        budget: Max characters for context text (default 4000).
    """
    try:
        result = recall(query=query, project=project, budget=budget)
        return _json_response(result)
    except Exception as e:
        return _json_response({"error": str(e)})


# ---------------------------------------------------------------------------
# Tool 2: forge_project_context — Full project state
# ---------------------------------------------------------------------------

@mcp.tool()
def forge_project_context(
    project: str,
    sections: Optional[str] = None,
) -> str:
    """Get full project state: decisions, threads, flags, stale items, conflicts.

    Args:
        project: Project display name (e.g. "The Reality Compiler").
        sections: Comma-separated section names. Default: all.
            Options: decisions, threads, flags, stale, conflicts
    """
    try:
        section_list = None
        if sections:
            section_list = [s.strip() for s in sections.split(",")]
        result = project_context(project=project, sections=section_list)
        return _json_response(result)
    except Exception as e:
        return _json_response({"error": str(e)})


# ---------------------------------------------------------------------------
# Tool 2b: forge_context_load — One-call conversation bootstrap
# ---------------------------------------------------------------------------

@mcp.tool()
def forge_context_load(
    project: str,
    query: Optional[str] = None,
    budget: Optional[int] = None,
) -> str:
    """One-call conversation bootstrap: project state + optional query recall.

    Call this at the start of every conversation. Returns the full project
    state (decisions, threads, flags, stale items, conflicts) in one shot.
    If a query is provided, also includes attention-weighted recall results
    for that topic.

    Args:
        project: Project display name (e.g. "The Reality Compiler").
        query: Optional search query for additional context recall.
        budget: Max chars for combined context (default 6000).
    """
    try:
        result = context_load(project=project, query=query, budget=budget)
        return _json_response(result)
    except Exception as e:
        return _json_response({"error": str(e)})


# ---------------------------------------------------------------------------
# Tool 3: forge_entanglement — Cross-project resonances
# ---------------------------------------------------------------------------

@mcp.tool()
def forge_entanglement(
    query: Optional[str] = None,
    project: Optional[str] = None,
) -> str:
    """Get cross-project entanglement data: clusters, bridges, loose ends.

    Returns the latest cached entanglement scan, optionally filtered
    by project. If a query is provided, filters clusters to those
    containing items matching the query text.

    Args:
        query: Optional text to filter clusters by relevance.
        project: Optional project name to filter.
    """
    try:
        scan = get_latest_scan(project=project)
        if scan is None:
            return _json_response({
                "clusters": [],
                "bridges": [],
                "loose_ends": [],
                "note": "No entanglement scan cached. Run a scan first.",
            })

        if query:
            query_lower = query.lower()
            filtered_clusters = [
                c for c in scan.get("clusters", [])
                if any(
                    query_lower in (item.get("text", "").lower())
                    for item in c.get("items", [])
                )
            ]
            scan = {**scan, "clusters": filtered_clusters}

        return _json_response(scan)
    except Exception as e:
        return _json_response({"error": str(e)})


# ---------------------------------------------------------------------------
# Tool 4: forge_trace — Lineage traversal
# ---------------------------------------------------------------------------

@mcp.tool()
def forge_trace(conversation_id: str) -> str:
    """Trace the lineage of a conversation: ancestors and descendants.

    Walks backward and forward through compression hops to show the
    full chain of conversations, including which decisions and threads
    were carried or dropped at each hop.

    Args:
        conversation_id: Conversation identifier (UUID, source ID,
            name prefix, or substring).
    """
    try:
        conv = resolve_id(conversation_id)
        if conv is None:
            return _json_response({"error": f"Conversation not found: {conversation_id}"})

        trace = trace_conversation(conv["uuid"])
        trace["conversation"] = conv
        return _json_response(trace)
    except Exception as e:
        return _json_response({"error": str(e)})


# ---------------------------------------------------------------------------
# Tool 5: forge_alerts — System-wide alerts
# ---------------------------------------------------------------------------

@mcp.tool()
def forge_alerts() -> str:
    """Get system-wide alerts: stale items, conflicts, pending flags, loose ends.

    Returns counts for each alert category across all projects.
    """
    try:
        result = alerts()
        return _json_response(result)
    except Exception as e:
        return _json_response({"error": str(e)})


# ---------------------------------------------------------------------------
# Tool 6: forge_search — Scoped semantic search
# ---------------------------------------------------------------------------

@mcp.tool()
def forge_search(
    query: str,
    scope: Optional[str] = None,
    limit: Optional[int] = None,
) -> str:
    """Semantic vector search within a specific collection.

    Unlike forge_recall (which searches all collections with attention
    scoring), this searches a single collection for raw similarity results.

    Args:
        query: Search query text.
        scope: Collection to search. Options: conversations, messages,
            decisions, patterns. Default: conversations.
        limit: Max results (default 10, max 50).
    """
    try:
        from vectordb.config import (
            COLLECTION_CONVERSATIONS,
            COLLECTION_DECISION_REGISTRY,
            COLLECTION_MESSAGES,
            COLLECTION_PATTERNS,
        )

        scope_map = {
            "conversations": COLLECTION_CONVERSATIONS,
            "messages": COLLECTION_MESSAGES,
            "decisions": COLLECTION_DECISION_REGISTRY,
            "patterns": COLLECTION_PATTERNS,
        }

        scope = scope or "conversations"
        collection_name = scope_map.get(scope)
        if collection_name is None:
            return _json_response({
                "error": f"Invalid scope '{scope}'. Use: {', '.join(scope_map.keys())}"
            })

        search_limit = min(limit or 10, 50)
        results = vector_search(
            query=query,
            collection_name=collection_name,
            limit=search_limit,
        )
        return _json_response(results)
    except Exception as e:
        return _json_response({"error": str(e)})


# ---------------------------------------------------------------------------
# Tool 7: forge_decide — Register a decision
# ---------------------------------------------------------------------------

@mcp.tool()
def forge_decide(
    text: str,
    project: str,
    local_id: str,
    tier: Optional[float] = None,
    rationale: Optional[str] = None,
) -> str:
    """Register a decision in Forge OS with automatic conflict detection.

    The decision is embedded via VoyageAI, assigned a deterministic UUID,
    and checked against existing decisions for conflicts.

    Args:
        text: Full decision text.
        project: Project display name.
        local_id: Archive-local identifier (e.g. "D042").
        tier: Epistemic confidence tier (0.0-1.0). Optional.
        rationale: Optional rationale text explaining the decision.
    """
    try:
        from vectordb.conversation_registry import list_projects as _list_projects
        from vectordb.decision_registry import upsert_decision
        from vectordb.uuidv8 import v5

        projects = _list_projects()
        project_info = next((p for p in projects if p["project_name"] == project), None)

        if project_info is None:
            return _json_response({"error": f"Project not found: {project}"})

        import uuid as uuid_mod
        project_uuid = uuid_mod.UUID(project_info["project_uuid"])

        conversations = None
        try:
            from vectordb.conversation_registry import list_project_conversations
            conversations = list_project_conversations(project)
        except Exception:
            pass

        conv_id = uuid_mod.UUID(int=0)
        if conversations:
            conv_id = uuid_mod.UUID(conversations[0].get("uuid", str(uuid_mod.UUID(int=0))))

        result = upsert_decision(
            local_id=local_id,
            text=text,
            project=project,
            project_uuid=project_uuid,
            originated_conversation_id=conv_id,
            epistemic_tier=tier,
            rationale=rationale,
        )

        emit_event("forge.mcp.decide", {
            "uuid": result.get("uuid"),
            "project": project,
            "local_id": local_id,
            "session": _SESSION_ID,
        })

        return _json_response(result)
    except Exception as e:
        return _json_response({"error": str(e)})


# ---------------------------------------------------------------------------
# Tool 8: forge_thread — Track/resolve threads
# ---------------------------------------------------------------------------

@mcp.tool()
def forge_thread(
    title: str,
    project: str,
    local_id: str,
    status: Optional[str] = None,
    priority: Optional[str] = None,
    resolution: Optional[str] = None,
) -> str:
    """Track an open question or resolve an existing thread.

    If the thread already exists (same title + project), updates it.
    If resolution is provided with status='resolved', closes the thread.

    Args:
        title: Thread title/question text.
        project: Project display name.
        local_id: Archive-local identifier (e.g. "T007").
        status: Thread status. Options: open, resolved, blocked. Default: open.
        priority: Priority level. Options: high, medium, low. Default: medium.
        resolution: Resolution text. Required if status is 'resolved'.
    """
    try:
        from vectordb.conversation_registry import list_projects as _list_projects
        from vectordb.thread_registry import resolve_thread, upsert_thread

        projects = _list_projects()
        project_info = next((p for p in projects if p["project_name"] == project), None)

        if project_info is None:
            return _json_response({"error": f"Project not found: {project}"})

        import uuid as uuid_mod
        project_uuid = uuid_mod.UUID(project_info["project_uuid"])

        conversations = None
        try:
            from vectordb.conversation_registry import list_project_conversations
            conversations = list_project_conversations(project)
        except Exception:
            pass

        conv_id = uuid_mod.UUID(int=0)
        if conversations:
            conv_id = uuid_mod.UUID(conversations[0].get("uuid", str(uuid_mod.UUID(int=0))))

        result = upsert_thread(
            local_id=local_id,
            title=title,
            project=project,
            project_uuid=project_uuid,
            first_seen_conversation_id=conv_id,
            status=status or "open",
            priority=priority or "medium",
            resolution=resolution,
        )

        if status == "resolved" and resolution and result.get("uuid"):
            resolve_thread(result["uuid"], resolution)
            result["action"] = "resolved"

        emit_event("forge.mcp.thread", {
            "uuid": result.get("uuid"),
            "project": project,
            "local_id": local_id,
            "session": _SESSION_ID,
        })

        return _json_response(result)
    except Exception as e:
        return _json_response({"error": str(e)})


# ---------------------------------------------------------------------------
# Tool 9: forge_flag — Plant expedition flag
# ---------------------------------------------------------------------------

@mcp.tool()
def forge_flag(
    description: str,
    project: str,
    category: Optional[str] = None,
    context: Optional[str] = None,
) -> str:
    """Bookmark an observation or finding for future expedition compilation.

    Flags survive context compression and session boundaries. They can
    later be compiled into priming blocks.

    Args:
        description: What was observed/flagged.
        project: Project display name.
        category: Flag category. Options: inversion, isomorphism, fsd,
            manifestation, trap, general. Default: general.
        context: Optional surrounding context text.
    """
    try:
        from vectordb.conversation_registry import list_projects as _list_projects
        from vectordb.expedition_flags import plant_flag

        projects = _list_projects()
        project_info = next((p for p in projects if p["project_name"] == project), None)

        if project_info is None:
            return _json_response({"error": f"Project not found: {project}"})

        import uuid as uuid_mod
        project_uuid = uuid_mod.UUID(project_info["project_uuid"])

        conversations = None
        try:
            from vectordb.conversation_registry import list_project_conversations
            conversations = list_project_conversations(project)
        except Exception:
            pass

        conv_id = str(uuid_mod.UUID(int=0))
        if conversations:
            conv_id = conversations[0].get("uuid", conv_id)

        result = plant_flag(
            description=description,
            project=project,
            project_uuid=project_uuid,
            conversation_id=conv_id,
            category=category,
            context=context,
        )

        emit_event("forge.mcp.flag", {
            "uuid": result.get("uuid"),
            "project": project,
            "session": _SESSION_ID,
        })

        return _json_response(result)
    except Exception as e:
        return _json_response({"error": str(e)})


# ---------------------------------------------------------------------------
# Tool 10: forge_pattern — Store learned pattern
# ---------------------------------------------------------------------------

@mcp.tool()
def forge_pattern(
    content: str,
    pattern_type: str,
    success_score: float,
) -> str:
    """Store a learned pattern in the pattern registry.

    If a similar pattern exists (>0.9 similarity), merges via weighted
    average of success scores. Otherwise inserts a new pattern.

    Args:
        content: Pattern content text.
        pattern_type: Pattern type. Options: routing, execution,
            error_recovery, optimization.
        success_score: How successful this pattern was (0.0-1.0).
    """
    try:
        from vectordb.patterns import pattern_store

        result = pattern_store(
            content=content,
            pattern_type=pattern_type,
            success_score=success_score,
        )

        emit_event("forge.mcp.pattern", {
            "pattern_id": result.get("pattern_id"),
            "action": result.get("action"),
            "session": _SESSION_ID,
        })

        return _json_response(result)
    except Exception as e:
        return _json_response({"error": str(e)})


# ---------------------------------------------------------------------------
# Tool 11: forge_remember — Session scratchpad
# ---------------------------------------------------------------------------

@mcp.tool()
def forge_remember(key: str, value: str) -> str:
    """Store a key-value pair in the session scratchpad.

    Values persist for the MCP server's lifetime (TTL: 1 hour in MongoDB).
    Use for session-scoped notes, intermediate results, or conversation state.

    Args:
        key: Key name.
        value: Value to store (will be JSON-serialized).
    """
    try:
        scratchpad_set(_SESSION_ID, key, value)
        return _json_response({
            "action": "stored",
            "key": key,
            "session_id": _SESSION_ID,
        })
    except Exception as e:
        return _json_response({"error": str(e)})


# ---------------------------------------------------------------------------
# Tool 12: forge_session — Get session state
# ---------------------------------------------------------------------------

@mcp.tool()
def forge_session() -> str:
    """Get all key-value pairs stored in the current session scratchpad."""
    try:
        entries = scratchpad_list(_SESSION_ID)
        return _json_response({
            "session_id": _SESSION_ID,
            "entries": entries,
            "count": len(entries),
        })
    except Exception as e:
        return _json_response({"error": str(e)})


# ---------------------------------------------------------------------------
# Tool 13: forge_stats — System overview
# ---------------------------------------------------------------------------

@mcp.tool()
def forge_stats() -> str:
    """Get Forge OS system overview: counts for all major collections."""
    try:
        db = get_database()
        latest_scan = db["entanglement_scans"].find_one(
            {"project": {"$exists": False}},
            {"_id": 0, "resonances_found": 1, "scanned_at": 1, "by_tier": 1},
            sort=[("scanned_at", -1)],
        )
        entanglement_stats = {
            "resonances": latest_scan.get("resonances_found", 0) if latest_scan else 0,
            "last_scanned": latest_scan.get("scanned_at") if latest_scan else None,
        }

        return _json_response({
            "conversations": db["conversation_registry"].count_documents({}),
            "projects": len(list_projects()),
            "decisions": db["decision_registry"].count_documents({"status": "active"}),
            "threads": db["thread_registry"].count_documents({"status": {"$ne": "resolved"}}),
            "edges": db["lineage_edges"].count_documents({}),
            "flags": db["expedition_flags"].count_documents({"status": "pending"}),
            "compressions": db["compression_registry"].count_documents({}),
            "priming_blocks": db["priming_registry"].count_documents({"status": "active"}),
            "patterns": db["patterns"].count_documents({}),
            "entanglement": entanglement_stats,
            "session_id": _SESSION_ID,
        })
    except Exception as e:
        return _json_response({"error": str(e)})


# ---------------------------------------------------------------------------
# Tool 14: forge_projects — Project listing
# ---------------------------------------------------------------------------

@mcp.tool()
def forge_projects() -> str:
    """List all Forge OS projects with decision/thread/flag counts."""
    try:
        db = get_database()
        projects = list_projects(db=db)

        for p in projects:
            name = p["project_name"]
            p["decision_count"] = db["decision_registry"].count_documents(
                {"project": name, "status": "active"}
            )
            p["thread_count"] = db["thread_registry"].count_documents(
                {"project": name, "status": {"$ne": "resolved"}}
            )
            p["flag_count"] = db["expedition_flags"].count_documents(
                {"project": name, "status": "pending"}
            )

        return _json_response(projects)
    except Exception as e:
        return _json_response({"error": str(e)})


# ---------------------------------------------------------------------------
# Tool 15: forge_orchestrate — Gravity-assisted multi-lens recall
# ---------------------------------------------------------------------------

@mcp.tool()
def forge_orchestrate(
    query: str,
    lens_name: Optional[str] = None,
    lenses: Optional[str] = None,
    budget: Optional[int] = None,
) -> str:
    """Multi-lens gravity-assisted recall across project roles.

    Runs attention-weighted recall through multiple project lenses in
    parallel, then detects convergence (where lenses agree) and divergence
    (where they disagree). Returns a combined gravity field with coherence
    score.

    Args:
        query: What to search for (natural language).
        lens_name: Named lens configuration to use (e.g. "gravity-assist").
        lenses: JSON array of lens objects [{project_name, role, weight?}, ...].
            Overrides lens_name if both provided.
        budget: Max characters for combined output (default 6000).
    """
    try:
        parsed_lenses = None
        if lenses:
            parsed_lenses = json.loads(lenses)

        result = gravity_orchestrate(
            query=query,
            lenses=parsed_lenses,
            lens_name=lens_name,
            budget=budget,
        )

        emit_event("forge.mcp.orchestrate", {
            "query": query[:100],
            "lens_name": lens_name,
            "lens_count": len(result.get("lenses_used", [])),
            "coherence": result.get("field_summary", {}).get("field_coherence"),
            "session": _SESSION_ID,
        })

        return _json_response(result)
    except Exception as e:
        return _json_response({"error": str(e)})


# ---------------------------------------------------------------------------
# Tool 16: forge_roles — Manage project role assignments
# ---------------------------------------------------------------------------

@mcp.tool()
def forge_roles(
    action: str,
    project_name: Optional[str] = None,
    role: Optional[str] = None,
    weight: Optional[float] = None,
    description: Optional[str] = None,
) -> str:
    """Manage project epistemic role assignments for gravity assist.

    Roles define how a project's knowledge bends the LLM probability field.
    Available roles: connector, navigator, builder, evaluator, critic, compiler.

    Args:
        action: Operation to perform. Options: list, get, assign, remove.
        project_name: Project display name (required for get/assign/remove).
        role: Role type (required for assign).
        weight: Role weight 0.0-1.0 (optional, default 1.0).
        description: Custom role description override (optional).
    """
    try:
        if action == "list":
            return _json_response(list_roles())

        if action == "get":
            if not project_name:
                return _json_response({"error": "project_name required for 'get'"})
            result = get_role(project_name)
            if result is None:
                return _json_response({"error": f"No role assigned to '{project_name}'"})
            return _json_response(result)

        if action == "assign":
            if not project_name or not role:
                return _json_response({"error": "project_name and role required for 'assign'"})
            result = assign_role(
                project_name=project_name,
                role=role,
                weight=weight if weight is not None else 1.0,
                description=description,
            )
            return _json_response(result)

        if action == "remove":
            if not project_name:
                return _json_response({"error": "project_name required for 'remove'"})
            return _json_response(remove_role(project_name))

        return _json_response({"error": f"Unknown action '{action}'. Use: list, get, assign, remove"})
    except Exception as e:
        return _json_response({"error": str(e)})


# ---------------------------------------------------------------------------
# Tool 17: forge_lenses — Manage named lens configurations
# ---------------------------------------------------------------------------

@mcp.tool()
def forge_lenses(
    action: str,
    lens_name: Optional[str] = None,
    projects: Optional[str] = None,
    description: Optional[str] = None,
    default_budget: Optional[int] = None,
) -> str:
    """Manage named lens configurations for gravity-assisted orchestration.

    A lens is a reusable set of project-role assignments. For example,
    the "gravity-assist" lens pairs The Nexus (connector) with
    The Cartographer's Codex (navigator).

    Args:
        action: Operation to perform. Options: list, get, save, delete.
        lens_name: Lens name (required for get/save/delete).
        projects: JSON array of [{project_name, role, weight?}] for save.
        description: Human-readable lens description (for save).
        default_budget: Default budget in chars (for save, default 6000).
    """
    try:
        if action == "list":
            return _json_response(list_lenses())

        if action == "get":
            if not lens_name:
                return _json_response({"error": "lens_name required for 'get'"})
            result = get_lens(lens_name)
            if result is None:
                return _json_response({"error": f"Lens not found: '{lens_name}'"})
            return _json_response(result)

        if action == "save":
            if not lens_name or not projects:
                return _json_response({"error": "lens_name and projects required for 'save'"})
            parsed_projects = json.loads(projects)
            result = save_lens(
                lens_name=lens_name,
                projects=parsed_projects,
                description=description,
                default_budget=default_budget or 6000,
            )
            return _json_response(result)

        if action == "delete":
            if not lens_name:
                return _json_response({"error": "lens_name required for 'delete'"})
            return _json_response(delete_lens(lens_name))

        return _json_response({"error": f"Unknown action '{action}'. Use: list, get, save, delete"})
    except Exception as e:
        return _json_response({"error": str(e)})


# ---------------------------------------------------------------------------
# Tool 18: forge_blob_stats — Blob store statistics
# ---------------------------------------------------------------------------

@mcp.tool()
def forge_blob_stats() -> str:
    """Return content-addressed blob store statistics.

    Shows blob count, total size in bytes, and backend type (local or gcs).
    """
    try:
        from vectordb.blob_store import blob_stats
        return _json_response(blob_stats())
    except Exception as e:
        return _json_response({"error": str(e)})


@mcp.tool()
def forge_resolve_display_id(display_id: str) -> str:
    """Resolve a global display ID (e.g. FORGE-D-0042) to its entity UUID and collection.

    Use this when you encounter a human-readable display ID and need the underlying entity.
    Returns entity_uuid, collection name, and project.
    """
    try:
        from vectordb.display_ids import resolve_display_id
        result = resolve_display_id(display_id)
        if result is None:
            return _json_response({"error": f"Display ID '{display_id}' not found"})
        return _json_response(result)
    except Exception as e:
        return _json_response({"error": str(e)})


@mcp.tool()
def forge_backfill_display_ids(project: str) -> str:
    """Assign global display IDs to all existing decisions and threads that lack one.

    Run this once per project to backfill display IDs for entities created before
    the display ID system was added. Processes in created_at order.
    """
    try:
        from vectordb.display_ids import bulk_backfill
        from vectordb.config import COLLECTION_DECISION_REGISTRY, COLLECTION_THREAD_REGISTRY

        decision_count = bulk_backfill(project, "decision", COLLECTION_DECISION_REGISTRY)
        thread_count = bulk_backfill(project, "thread", COLLECTION_THREAD_REGISTRY)
        return _json_response({
            "project": project,
            "decisions_backfilled": decision_count,
            "threads_backfilled": thread_count,
        })
    except Exception as e:
        return _json_response({"error": str(e)})


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run()
