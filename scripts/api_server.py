"""Forge OS Mission Control — FastAPI server wrapping vectordb/ query functions.

Thin passthrough layer: each endpoint is 5-10 lines calling existing functions.
No new query logic. The vectordb module is the single source of truth.

Usage:
    python scripts/api_server.py
    # or: uvicorn scripts.api_server:app --port 8000 --reload
"""

import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

# Ensure project root is on sys.path so `import vectordb` works
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from vectordb.config import (
    COLLECTION_CONVERSATIONS,
    COLLECTION_DECISION_REGISTRY,
    COLLECTION_MESSAGES,
    COLLECTION_PATTERNS,
)
from vectordb.conversation_registry import (
    get_conversation_by_uuid,
    list_project_conversations,
    list_projects,
    resolve_id,
)
from vectordb.compression_registry import list_compressions
from vectordb.conflicts import detect_conflicts
from vectordb.db import get_database
from vectordb.decision_registry import get_active_decisions, get_stale_decisions
from vectordb.expedition_flags import get_all_flags, get_pending_flags
from vectordb.lineage import get_full_graph, trace_conversation
from vectordb.priming_registry import list_priming_blocks
from vectordb.thread_registry import get_active_threads, get_stale_threads
from vectordb.vector_store import vector_search
from vectordb.claude_api import ClaudeAPIError, ClaudeSession, get_session, reset_session
from vectordb.sync_manifest import load_manifest, resolve_all_targets, validate_manifest
from vectordb.sync_engine import sync_all, sync_one


# ---------------------------------------------------------------------------
# Name resolution: conversation registry names → decision/thread/flag names
# ---------------------------------------------------------------------------

def _build_name_map() -> dict[str, list[str]]:
    """Build a mapping from conversation-registry names to the names used in
    decision/thread/flag registries, sourced from the sync manifest name_map.

    Returns:
        Dict mapping conv-registry name → list of internal names.
        Names not in the map are returned as-is.
    """
    try:
        manifest = load_manifest()
        return manifest.get("name_map", {})
    except (FileNotFoundError, ValueError):
        return {}


def _resolve_names(conv_name: str) -> list[str]:
    """Resolve a conversation-registry project name to the name(s)
    used in decision/thread/flag registries.

    Falls back to returning the original name if no mapping exists.
    """
    name_map = _build_name_map()
    mapped = name_map.get(conv_name)
    if mapped is None:
        return [conv_name]
    if mapped == ["*"]:
        return [conv_name]
    return list(mapped)


app = FastAPI(
    title="Forge OS Mission Control API",
    description="REST wrapper over vectordb/ query functions",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _serialize(obj):
    """Recursively convert MongoDB-unfriendly types for JSON serialization."""
    if isinstance(obj, dict):
        return {k: _serialize(v) for k, v in obj.items() if k != "_id"}
    if isinstance(obj, list):
        return [_serialize(item) for item in obj]
    if isinstance(obj, set):
        return sorted(_serialize(item) for item in obj)
    if isinstance(obj, datetime):
        return obj.isoformat()
    return obj


def _json(data):
    return JSONResponse(content=_serialize(data))


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

@app.get("/api/stats")
def api_stats():
    db = get_database()
    return _json({
        "conversations": db["conversation_registry"].count_documents({}),
        "projects": len(list_projects()),
        "decisions": db["decision_registry"].count_documents({"status": "active"}),
        "threads": db["thread_registry"].count_documents({"status": {"$ne": "resolved"}}),
        "edges": db["lineage_edges"].count_documents({}),
        "flags": db["expedition_flags"].count_documents({"status": "pending"}),
        "compressions": db["compression_registry"].count_documents({}),
        "priming_blocks": db["priming_registry"].count_documents({"status": "active"}),
    })


# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------

@app.get("/api/projects")
def api_projects():
    projects = list_projects()

    # Enrich with decision + thread counts per project
    # Uses name resolution since registries may use different names
    db = get_database()
    for p in projects:
        internal_names = _resolve_names(p["project_name"])
        p["decision_count"] = db["decision_registry"].count_documents(
            {"project": {"$in": internal_names}, "status": "active"}
        )
        p["thread_count"] = db["thread_registry"].count_documents(
            {"project": {"$in": internal_names}, "status": {"$ne": "resolved"}}
        )
        p["flag_count"] = db["expedition_flags"].count_documents(
            {"project": {"$in": internal_names}, "status": "pending"}
        )

    return _json(projects)


@app.get("/api/projects/{name}/conversations")
def api_project_conversations(name: str):
    return _json(list_project_conversations(name))


@app.get("/api/projects/{name}/decisions")
def api_project_decisions(name: str):
    results = []
    for internal_name in _resolve_names(name):
        results.extend(get_active_decisions(internal_name))
    return _json(results)


@app.get("/api/projects/{name}/threads")
def api_project_threads(name: str):
    results = []
    for internal_name in _resolve_names(name):
        results.extend(get_active_threads(internal_name))
    return _json(results)


@app.get("/api/projects/{name}/stale")
def api_project_stale(name: str):
    all_decisions = []
    all_threads = []
    for internal_name in _resolve_names(name):
        all_decisions.extend(get_stale_decisions(internal_name))
        all_threads.extend(get_stale_threads(internal_name))
    return _json({
        "decisions": all_decisions,
        "threads": all_threads,
    })


@app.get("/api/projects/{name}/flags")
def api_project_flags(name: str):
    results = []
    for internal_name in _resolve_names(name):
        results.extend(get_all_flags(internal_name))
    return _json(results)


@app.get("/api/projects/{name}/priming")
def api_project_priming(name: str):
    return _json(list_priming_blocks(name))


@app.get("/api/projects/{name}/compressions")
def api_project_compressions(name: str, limit: int = 50):
    return _json(list_compressions(name, limit=limit))


# ---------------------------------------------------------------------------
# Decisions (cross-project)
# ---------------------------------------------------------------------------

@app.get("/api/decisions")
def api_all_decisions():
    projects = list_projects()
    all_decisions = []
    for p in projects:
        all_decisions.extend(get_active_decisions(p["project_name"]))
    return _json(all_decisions)


@app.get("/api/decisions/conflicts")
def api_conflicting_decisions():
    db = get_database()
    results = list(db["decision_registry"].find(
        {"status": "active", "conflicts_with": {"$ne": []}},
        {"_id": 0, "embedding": 0},
    ))
    return _json(results)


# ---------------------------------------------------------------------------
# Threads (cross-project)
# ---------------------------------------------------------------------------

@app.get("/api/threads")
def api_all_threads():
    projects = list_projects()
    all_threads = []
    for p in projects:
        all_threads.extend(get_active_threads(p["project_name"]))
    return _json(all_threads)


# ---------------------------------------------------------------------------
# Lineage
# ---------------------------------------------------------------------------

@app.get("/api/lineage/graph")
def api_lineage_graph(project: Optional[str] = None):
    edges = get_full_graph(project=project)

    node_ids = set()
    for edge in edges:
        node_ids.add(edge["source_conversation"])
        node_ids.add(edge["target_conversation"])

    nodes = []
    for nid in node_ids:
        conv = get_conversation_by_uuid(nid)
        nodes.append({
            "id": nid,
            "name": conv["conversation_name"] if conv else nid[:8],
            "project": conv["project_name"] if conv else "",
            "created_at": conv.get("created_at") if conv else None,
        })

    graph_edges = [
        {
            "source": e["source_conversation"],
            "target": e["target_conversation"],
            "compression_tag": e.get("compression_tag", ""),
            "cross_project": e.get("source_project", "") != e.get("target_project", ""),
            "decisions_carried": len(e.get("decisions_carried", [])),
            "decisions_dropped": len(e.get("decisions_dropped", [])),
            "threads_carried": len(e.get("threads_carried", [])),
            "threads_resolved": len(e.get("threads_resolved", [])),
        }
        for e in edges
    ]

    return _json({"nodes": nodes, "edges": graph_edges})


@app.get("/api/lineage/trace/{identifier}")
def api_lineage_trace(identifier: str):
    conv = resolve_id(identifier)
    if conv is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    trace = trace_conversation(conv["uuid"])
    trace["conversation"] = conv
    return _json(trace)


# ---------------------------------------------------------------------------
# Conversations
# ---------------------------------------------------------------------------

@app.get("/api/conversations/{identifier}")
def api_conversation(identifier: str):
    conv = resolve_id(identifier)
    if conv is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return _json(conv)


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

SCOPE_MAP = {
    "conversations": COLLECTION_CONVERSATIONS,
    "messages": COLLECTION_MESSAGES,
    "decisions": COLLECTION_DECISION_REGISTRY,
    "patterns": COLLECTION_PATTERNS,
}


@app.get("/api/search")
def api_search(
    q: str = Query(..., min_length=1),
    scope: str = Query("conversations"),
    limit: int = Query(10, ge=1, le=50),
):
    collection_name = SCOPE_MAP.get(scope)
    if collection_name is None:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid scope '{scope}'. Use: {', '.join(SCOPE_MAP.keys())}",
        )

    results = vector_search(
        query=q,
        collection_name=collection_name,
        limit=limit,
    )
    return _json(results)


# ---------------------------------------------------------------------------
# Alerts (aggregated for dashboard)
# ---------------------------------------------------------------------------

@app.get("/api/alerts")
def api_alerts():
    projects = list_projects()
    stale_decisions = []
    stale_threads = []
    total_pending_flags = 0

    for p in projects:
        name = p["project_name"]
        stale_decisions.extend(get_stale_decisions(name))
        stale_threads.extend(get_stale_threads(name))
        total_pending_flags += len(get_pending_flags(name))

    db = get_database()
    conflict_count = db["decision_registry"].count_documents(
        {"status": "active", "conflicts_with": {"$ne": []}}
    )

    return _json({
        "stale_decisions": len(stale_decisions),
        "stale_threads": len(stale_threads),
        "conflicts": conflict_count,
        "pending_flags": total_pending_flags,
    })


# ---------------------------------------------------------------------------
# Claude.ai Write-Back (project docs + instructions)
# ---------------------------------------------------------------------------

class UpdateInstructionsBody(BaseModel):
    prompt_template: str


class UpsertDocBody(BaseModel):
    file_name: str
    content: str


class UpdateDocBody(BaseModel):
    file_name: Optional[str] = None
    content: Optional[str] = None


def _get_claude_session() -> ClaudeSession:
    """Get a ClaudeSession, raising HTTP 503 if auth fails."""
    try:
        return get_session()
    except (FileNotFoundError, RuntimeError) as err:
        raise HTTPException(
            status_code=503,
            detail=f"Claude.ai auth unavailable: {err}",
        )


@app.get("/api/claude/projects")
def api_claude_projects():
    """List projects from Claude.ai (live, not from MongoDB)."""
    session = _get_claude_session()
    try:
        return _json(session.list_projects())
    except ClaudeAPIError as err:
        raise HTTPException(status_code=err.status_code, detail=str(err))


@app.get("/api/claude/projects/{project_uuid}")
def api_claude_project_detail(project_uuid: str):
    """Get full project detail from Claude.ai."""
    session = _get_claude_session()
    try:
        return _json(session.get_project(project_uuid))
    except ClaudeAPIError as err:
        raise HTTPException(status_code=err.status_code, detail=str(err))


@app.get("/api/claude/projects/{project_uuid}/docs")
def api_claude_project_docs(project_uuid: str):
    """Get knowledge docs from Claude.ai project."""
    session = _get_claude_session()
    try:
        return _json(session.get_project_docs(project_uuid))
    except ClaudeAPIError as err:
        raise HTTPException(status_code=err.status_code, detail=str(err))


@app.put("/api/claude/projects/{project_uuid}/instructions")
def api_claude_update_instructions(
    project_uuid: str, body: UpdateInstructionsBody
):
    """Update a Claude.ai project's custom instructions."""
    session = _get_claude_session()
    try:
        result = session.update_project_instructions(
            project_uuid, body.prompt_template
        )
        return _json(result or {"status": "updated"})
    except ClaudeAPIError as err:
        raise HTTPException(status_code=err.status_code, detail=str(err))


@app.post("/api/claude/projects/{project_uuid}/docs")
def api_claude_create_doc(project_uuid: str, body: UpsertDocBody):
    """Create a new knowledge doc in a Claude.ai project."""
    session = _get_claude_session()
    try:
        return _json(session.create_doc(project_uuid, body.file_name, body.content))
    except ClaudeAPIError as err:
        raise HTTPException(status_code=err.status_code, detail=str(err))


@app.put("/api/claude/projects/{project_uuid}/docs/{doc_uuid}")
def api_claude_update_doc(
    project_uuid: str, doc_uuid: str, body: UpdateDocBody
):
    """Update an existing knowledge doc in a Claude.ai project."""
    session = _get_claude_session()
    try:
        result = session.update_doc(
            project_uuid, doc_uuid, file_name=body.file_name, content=body.content
        )
        return _json(result or {"status": "updated"})
    except ClaudeAPIError as err:
        raise HTTPException(status_code=err.status_code, detail=str(err))


@app.delete("/api/claude/projects/{project_uuid}/docs/{doc_uuid}")
def api_claude_delete_doc(project_uuid: str, doc_uuid: str):
    """Delete a knowledge doc from a Claude.ai project."""
    session = _get_claude_session()
    try:
        session.delete_doc(project_uuid, doc_uuid)
        return _json({"status": "deleted"})
    except ClaudeAPIError as err:
        raise HTTPException(status_code=err.status_code, detail=str(err))


@app.post("/api/claude/projects/{project_uuid}/docs/upsert")
def api_claude_upsert_doc(project_uuid: str, body: UpsertDocBody):
    """Create or update a doc by filename (matches existing file_name)."""
    session = _get_claude_session()
    try:
        return _json(session.upsert_doc(project_uuid, body.file_name, body.content))
    except ClaudeAPIError as err:
        raise HTTPException(status_code=err.status_code, detail=str(err))


@app.post("/api/claude/sync/{project_uuid}")
def api_claude_sync_project(project_uuid: str, project_name: str = Query(...)):
    """Sync Forge OS decisions + threads to a Claude.ai project as knowledge docs."""
    session = _get_claude_session()
    try:
        result = session.sync_all_to_project(project_uuid, project_name)
        return _json(result)
    except ClaudeAPIError as err:
        raise HTTPException(status_code=err.status_code, detail=str(err))


@app.post("/api/claude/reset-session")
def api_claude_reset_session():
    """Force re-read cookies (e.g. after Firefox login refresh)."""
    reset_session()
    return _json({"status": "session_reset"})


# ---------------------------------------------------------------------------
# Manifest Sync
# ---------------------------------------------------------------------------

@app.get("/api/sync/plan")
def api_sync_plan(manifest: Optional[str] = None):
    """Show the resolved sync plan (what goes where)."""
    try:
        m = load_manifest(manifest)
        targets = resolve_all_targets(m)
        return _json(targets)
    except (FileNotFoundError, ValueError) as err:
        raise HTTPException(status_code=400, detail=str(err))


@app.post("/api/sync/run")
def api_sync_run(
    dry_run: bool = Query(False),
    target: Optional[str] = Query(None),
    manifest: Optional[str] = Query(None),
):
    """Execute manifest sync. Optional dry_run and single-target mode."""
    try:
        if target:
            result = sync_one(target, dry_run=dry_run, manifest_path=manifest)
        else:
            result = sync_all(dry_run=dry_run, manifest_path=manifest)
        return _json(result)
    except (FileNotFoundError, ValueError) as err:
        raise HTTPException(status_code=400, detail=str(err))
    except ClaudeAPIError as err:
        raise HTTPException(status_code=err.status_code, detail=str(err))


@app.get("/api/sync/manifest")
def api_sync_manifest(manifest: Optional[str] = None):
    """Return the raw parsed manifest."""
    try:
        m = load_manifest(manifest)
        return _json(m)
    except (FileNotFoundError, ValueError) as err:
        raise HTTPException(status_code=400, detail=str(err))


@app.post("/api/sync/validate")
def api_sync_validate(manifest: Optional[str] = None):
    """Validate the manifest and return warnings."""
    try:
        m = load_manifest(manifest)
        warnings = validate_manifest(m)
        targets = resolve_all_targets(m)
        return _json({
            "valid": len(warnings) == 0,
            "warnings": warnings,
            "enabled_targets": len(targets),
        })
    except (FileNotFoundError, ValueError) as err:
        raise HTTPException(status_code=400, detail=str(err))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
