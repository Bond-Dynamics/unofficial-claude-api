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
from vectordb.attention import (
    alerts as attention_alerts,
    context_load as attention_context_load,
    project_context as attention_project_context,
    recall as attention_recall,
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
from vectordb.scratchpad import scratchpad_list, scratchpad_set


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
    latest_scan = db["entanglement_scans"].find_one(
        {"project": {"$exists": False}},
        {"_id": 0, "resonances_found": 1, "scanned_at": 1, "by_tier": 1},
        sort=[("scanned_at", -1)],
    )
    entanglement_stats = {
        "resonances": latest_scan.get("resonances_found", 0) if latest_scan else 0,
        "last_scanned": latest_scan.get("scanned_at") if latest_scan else None,
    }
    return _json({
        "conversations": db["conversation_registry"].count_documents({}),
        "projects": len(list_projects()),
        "decisions": db["decision_registry"].count_documents({"status": "active"}),
        "threads": db["thread_registry"].count_documents({"status": {"$ne": "resolved"}}),
        "edges": db["lineage_edges"].count_documents({}),
        "flags": db["expedition_flags"].count_documents({"status": "pending"}),
        "compressions": db["compression_registry"].count_documents({}),
        "priming_blocks": db["priming_registry"].count_documents({"status": "active"}),
        "entanglement": entanglement_stats,
    })


# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------

@app.get("/api/projects")
def api_projects():
    projects = list_projects()

    db = get_database()
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

    return _json(projects)


@app.get("/api/projects/{name}/conversations")
def api_project_conversations(name: str):
    return _json(list_project_conversations(name))


@app.get("/api/projects/{name}/decisions")
def api_project_decisions(name: str):
    return _json(get_active_decisions(name))


@app.get("/api/projects/{name}/threads")
def api_project_threads(name: str):
    return _json(get_active_threads(name))


@app.get("/api/projects/{name}/stale")
def api_project_stale(name: str):
    return _json({
        "decisions": get_stale_decisions(name),
        "threads": get_stale_threads(name),
    })


@app.get("/api/projects/{name}/flags")
def api_project_flags(name: str):
    return _json(get_all_flags(name))


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

    latest_scan = db["entanglement_scans"].find_one(
        {"project": {"$exists": False}},
        {"_id": 0, "loose_ends": 1, "resonances_found": 1, "scanned_at": 1},
        sort=[("scanned_at", -1)],
    )
    loose_end_count = len(latest_scan.get("loose_ends", [])) if latest_scan else 0
    resonance_count = latest_scan.get("resonances_found", 0) if latest_scan else 0

    return _json({
        "stale_decisions": len(stale_decisions),
        "stale_threads": len(stale_threads),
        "conflicts": conflict_count,
        "pending_flags": total_pending_flags,
        "entanglement_resonances": resonance_count,
        "entanglement_loose_ends": loose_end_count,
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
# Entanglement
# ---------------------------------------------------------------------------

@app.get("/api/entanglement")
def api_entanglement():
    """Get the latest cached entanglement scan. Returns 404 if no scan exists."""
    from vectordb.entanglement import get_latest_scan
    result = get_latest_scan()
    if result is None:
        raise HTTPException(
            status_code=404,
            detail="No entanglement scan found. POST /api/entanglement/scan to trigger one.",
        )
    return _json(result)


@app.post("/api/entanglement/scan")
def api_entanglement_trigger(min_similarity: Optional[float] = None):
    """Trigger a fresh full entanglement scan, persist, and return results."""
    from vectordb.entanglement import scan_and_save
    result = scan_and_save(min_similarity=min_similarity)
    return _json(result)


@app.get("/api/entanglement/project/{name}")
def api_entanglement_project(name: str):
    """Get the latest cached project-scoped scan. Returns 404 if none exists."""
    from vectordb.entanglement import get_latest_scan
    result = get_latest_scan(project=name)
    if result is None:
        raise HTTPException(
            status_code=404,
            detail=f"No entanglement scan found for '{name}'. "
                   f"POST /api/entanglement/project/{name}/scan to trigger one.",
        )
    return _json(result)


@app.post("/api/entanglement/project/{name}/scan")
def api_entanglement_project_trigger(
    name: str, min_similarity: Optional[float] = None,
):
    """Trigger a fresh project-scoped scan, persist, and return results."""
    from vectordb.entanglement import scan_project_and_save
    result = scan_project_and_save(name, min_similarity=min_similarity)
    return _json(result)


@app.get("/api/entanglement/clusters")
def api_entanglement_clusters():
    """Return just the clusters from the latest cached scan."""
    from vectordb.entanglement import get_latest_scan
    result = get_latest_scan()
    if result is None:
        return _json([])
    return _json(result.get("clusters", []))


@app.get("/api/entanglement/bridges")
def api_entanglement_bridges():
    """Return just the lineage bridges from the latest cached scan."""
    from vectordb.entanglement import get_latest_scan
    result = get_latest_scan()
    if result is None:
        return _json([])
    return _json(result.get("bridges", []))


@app.get("/api/entanglement/loose-ends")
def api_entanglement_loose_ends():
    """Return just the loose ends from the latest cached scan."""
    from vectordb.entanglement import get_latest_scan
    result = get_latest_scan()
    if result is None:
        return _json([])
    return _json(result.get("loose_ends", []))


@app.get("/api/entanglement/scans")
def api_entanglement_scan_history(limit: int = Query(20, ge=1, le=100)):
    """List recent scan summaries."""
    from vectordb.entanglement import list_scans
    return _json(list_scans(limit=limit))


@app.get("/api/entanglement/scans/{scan_id}")
def api_entanglement_scan_detail(scan_id: str):
    """Retrieve a specific historical scan by ID."""
    from vectordb.entanglement import get_scan
    result = get_scan(scan_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Scan not found")
    return _json(result)


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
# Forge OS Semantic Memory Interface (LLM-facing endpoints)
# ---------------------------------------------------------------------------

class ForgeRecallBody(BaseModel):
    query: str
    project: Optional[str] = None
    budget: Optional[int] = None


class ForgeProjectBody(BaseModel):
    project: str
    sections: Optional[list[str]] = None


class ForgeContextLoadBody(BaseModel):
    project: str
    query: Optional[str] = None
    budget: Optional[int] = None


class ForgeEntanglementBody(BaseModel):
    query: Optional[str] = None
    project: Optional[str] = None


class ForgeTraceBody(BaseModel):
    conversation_id: str


class ForgeSearchBody(BaseModel):
    query: str
    scope: Optional[str] = "conversations"
    limit: Optional[int] = 10


class ForgeDecideBody(BaseModel):
    text: str
    project: str
    local_id: str
    tier: Optional[float] = None
    rationale: Optional[str] = None


class ForgeThreadBody(BaseModel):
    title: str
    project: str
    local_id: str
    status: Optional[str] = "open"
    priority: Optional[str] = "medium"
    resolution: Optional[str] = None


class ForgeFlagBody(BaseModel):
    description: str
    project: str
    category: Optional[str] = None
    context: Optional[str] = None


class ForgePatternBody(BaseModel):
    content: str
    pattern_type: str
    success_score: float


class ForgeRememberBody(BaseModel):
    key: str
    value: str
    session_id: Optional[str] = None


class ForgeSessionBody(BaseModel):
    session_id: Optional[str] = None


@app.post("/api/forge/recall")
def api_forge_recall(body: ForgeRecallBody):
    result = attention_recall(
        query=body.query,
        project=body.project,
        budget=body.budget,
    )
    return _json(result)


@app.post("/api/forge/project")
def api_forge_project(body: ForgeProjectBody):
    result = attention_project_context(
        project=body.project,
        sections=body.sections,
    )
    return _json(result)


@app.post("/api/forge/context-load")
def api_forge_context_load(body: ForgeContextLoadBody):
    result = attention_context_load(
        project=body.project,
        query=body.query,
        budget=body.budget,
    )
    return _json(result)


@app.post("/api/forge/entanglement")
def api_forge_entanglement(body: ForgeEntanglementBody):
    from vectordb.entanglement import get_latest_scan as _get_latest_scan

    scan = _get_latest_scan(project=body.project)
    if scan is None:
        return _json({
            "clusters": [],
            "bridges": [],
            "loose_ends": [],
            "note": "No entanglement scan cached.",
        })

    if body.query:
        query_lower = body.query.lower()
        filtered_clusters = [
            c for c in scan.get("clusters", [])
            if any(
                query_lower in (item.get("text", "").lower())
                for item in c.get("items", [])
            )
        ]
        scan = {**scan, "clusters": filtered_clusters}

    return _json(scan)


@app.post("/api/forge/trace")
def api_forge_trace(body: ForgeTraceBody):
    conv = resolve_id(body.conversation_id)
    if conv is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    trace = trace_conversation(conv["uuid"])
    trace["conversation"] = conv
    return _json(trace)


@app.get("/api/forge/alerts")
def api_forge_alerts():
    result = attention_alerts()
    return _json(result)


@app.post("/api/forge/search")
def api_forge_search(body: ForgeSearchBody):
    scope_map = {
        "conversations": COLLECTION_CONVERSATIONS,
        "messages": COLLECTION_MESSAGES,
        "decisions": COLLECTION_DECISION_REGISTRY,
        "patterns": COLLECTION_PATTERNS,
    }

    collection_name = scope_map.get(body.scope)
    if collection_name is None:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid scope '{body.scope}'. Use: {', '.join(scope_map.keys())}",
        )

    search_limit = min(body.limit or 10, 50)
    results = vector_search(
        query=body.query,
        collection_name=collection_name,
        limit=search_limit,
    )
    return _json(results)


@app.post("/api/forge/decide")
def api_forge_decide(body: ForgeDecideBody):
    from vectordb.decision_registry import upsert_decision
    from vectordb.events import emit_event as _emit_event

    projects = list_projects()
    project_info = next(
        (p for p in projects if p["project_name"] == body.project), None
    )
    if project_info is None:
        raise HTTPException(status_code=404, detail=f"Project not found: {body.project}")

    import uuid as uuid_mod
    project_uuid = uuid_mod.UUID(project_info["project_uuid"])

    conversations = list_project_conversations(body.project)
    conv_id = uuid_mod.UUID(int=0)
    if conversations:
        conv_id = uuid_mod.UUID(conversations[0].get("uuid", str(uuid_mod.UUID(int=0))))

    result = upsert_decision(
        local_id=body.local_id,
        text=body.text,
        project=body.project,
        project_uuid=project_uuid,
        originated_conversation_id=conv_id,
        epistemic_tier=body.tier,
        rationale=body.rationale,
    )

    _emit_event("forge.api.decide", {
        "uuid": result.get("uuid"),
        "project": body.project,
        "local_id": body.local_id,
    })

    return _json(result)


@app.post("/api/forge/thread")
def api_forge_thread(body: ForgeThreadBody):
    from vectordb.thread_registry import resolve_thread as _resolve_thread
    from vectordb.thread_registry import upsert_thread
    from vectordb.events import emit_event as _emit_event

    projects = list_projects()
    project_info = next(
        (p for p in projects if p["project_name"] == body.project), None
    )
    if project_info is None:
        raise HTTPException(status_code=404, detail=f"Project not found: {body.project}")

    import uuid as uuid_mod
    project_uuid = uuid_mod.UUID(project_info["project_uuid"])

    conversations = list_project_conversations(body.project)
    conv_id = uuid_mod.UUID(int=0)
    if conversations:
        conv_id = uuid_mod.UUID(conversations[0].get("uuid", str(uuid_mod.UUID(int=0))))

    result = upsert_thread(
        local_id=body.local_id,
        title=body.title,
        project=body.project,
        project_uuid=project_uuid,
        first_seen_conversation_id=conv_id,
        status=body.status or "open",
        priority=body.priority or "medium",
        resolution=body.resolution,
    )

    if body.status == "resolved" and body.resolution and result.get("uuid"):
        _resolve_thread(result["uuid"], body.resolution)
        result["action"] = "resolved"

    _emit_event("forge.api.thread", {
        "uuid": result.get("uuid"),
        "project": body.project,
        "local_id": body.local_id,
    })

    return _json(result)


@app.post("/api/forge/flag")
def api_forge_flag(body: ForgeFlagBody):
    from vectordb.expedition_flags import plant_flag
    from vectordb.events import emit_event as _emit_event

    projects = list_projects()
    project_info = next(
        (p for p in projects if p["project_name"] == body.project), None
    )
    if project_info is None:
        raise HTTPException(status_code=404, detail=f"Project not found: {body.project}")

    import uuid as uuid_mod
    project_uuid = uuid_mod.UUID(project_info["project_uuid"])

    conversations = list_project_conversations(body.project)
    conv_id = str(uuid_mod.UUID(int=0))
    if conversations:
        conv_id = conversations[0].get("uuid", conv_id)

    result = plant_flag(
        description=body.description,
        project=body.project,
        project_uuid=project_uuid,
        conversation_id=conv_id,
        category=body.category,
        context=body.context,
    )

    _emit_event("forge.api.flag", {
        "uuid": result.get("uuid"),
        "project": body.project,
    })

    return _json(result)


@app.post("/api/forge/pattern")
def api_forge_pattern(body: ForgePatternBody):
    from vectordb.patterns import pattern_store

    result = pattern_store(
        content=body.content,
        pattern_type=body.pattern_type,
        success_score=body.success_score,
    )
    return _json(result)


@app.post("/api/forge/remember")
def api_forge_remember(body: ForgeRememberBody):
    session_id = body.session_id or "forge-api-default"
    scratchpad_set(session_id, body.key, body.value)
    return _json({
        "action": "stored",
        "key": body.key,
        "session_id": session_id,
    })


@app.post("/api/forge/session")
def api_forge_session(body: ForgeSessionBody):
    session_id = body.session_id or "forge-api-default"
    entries = scratchpad_list(session_id)
    return _json({
        "session_id": session_id,
        "entries": entries,
        "count": len(entries),
    })


@app.get("/api/forge/stats")
def api_forge_stats():
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

    return _json({
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
    })


@app.get("/api/forge/projects")
def api_forge_projects():
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

    return _json(projects)


# ---------------------------------------------------------------------------
# Blob Store
# ---------------------------------------------------------------------------

@app.get("/api/forge/blob-stats")
def api_forge_blob_stats():
    """Return content-addressed blob store statistics."""
    from vectordb.blob_store import blob_stats
    return _json(blob_stats())


# ---------------------------------------------------------------------------
# Gravity Assist (Layer 3.5)
# ---------------------------------------------------------------------------

class ForgeOrchestrateBody(BaseModel):
    query: str
    lens_name: Optional[str] = None
    lenses: Optional[list[dict]] = None
    budget: Optional[int] = None


class ForgeRoleAssignBody(BaseModel):
    project_name: str
    role: str
    weight: Optional[float] = 1.0
    description: Optional[str] = None


class ForgeLensSaveBody(BaseModel):
    lens_name: str
    projects: list[dict]
    description: Optional[str] = None
    default_budget: Optional[int] = 6000


@app.post("/api/forge/orchestrate")
def api_forge_orchestrate(body: ForgeOrchestrateBody):
    """Multi-lens gravity-assisted recall across project roles."""
    from vectordb.events import emit_event as _emit_event

    result = gravity_orchestrate(
        query=body.query,
        lenses=body.lenses,
        lens_name=body.lens_name,
        budget=body.budget,
    )

    _emit_event("forge.api.orchestrate", {
        "query": body.query[:100],
        "lens_name": body.lens_name,
        "lens_count": len(result.get("lenses_used", [])),
        "coherence": result.get("field_summary", {}).get("field_coherence"),
    })

    return _json(result)


@app.get("/api/forge/roles")
def api_forge_roles_list():
    """List all project role assignments."""
    return _json(list_roles())


@app.get("/api/forge/roles/{project_name}")
def api_forge_role_get(project_name: str):
    """Get the role assignment for a specific project."""
    result = get_role(project_name)
    if result is None:
        raise HTTPException(status_code=404, detail=f"No role assigned to '{project_name}'")
    return _json(result)


@app.post("/api/forge/roles")
def api_forge_role_assign(body: ForgeRoleAssignBody):
    """Assign an epistemic role to a project."""
    result = assign_role(
        project_name=body.project_name,
        role=body.role,
        weight=body.weight if body.weight is not None else 1.0,
        description=body.description,
    )
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return _json(result)


@app.delete("/api/forge/roles/{project_name}")
def api_forge_role_remove(project_name: str):
    """Remove a project's role assignment."""
    return _json(remove_role(project_name))


@app.get("/api/forge/lenses")
def api_forge_lenses_list():
    """List all saved lens configurations."""
    return _json(list_lenses())


@app.get("/api/forge/lenses/{lens_name}")
def api_forge_lens_get(lens_name: str):
    """Get a named lens configuration."""
    result = get_lens(lens_name)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Lens not found: '{lens_name}'")
    return _json(result)


@app.post("/api/forge/lenses")
def api_forge_lens_save(body: ForgeLensSaveBody):
    """Save a named lens configuration."""
    result = save_lens(
        lens_name=body.lens_name,
        projects=body.projects,
        description=body.description,
        default_budget=body.default_budget or 6000,
    )
    return _json(result)


@app.delete("/api/forge/lenses/{lens_name}")
def api_forge_lens_delete(lens_name: str):
    """Delete a named lens configuration."""
    return _json(delete_lens(lens_name))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
