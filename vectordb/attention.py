"""Forge OS Layer 3: ATTENTION — Attention-weighted cross-collection recall engine.

Provides LLM-agnostic semantic memory recall that goes beyond vector similarity.
Each result is scored by a multi-signal attention formula:

    attention = similarity * 0.45
              + epistemic_tier * 0.20
              + freshness * 0.15
              + conflict_salience * 0.10
              + category_boost * 0.10

This module has no MCP dependency. Both the MCP server and HTTP endpoints
call these functions directly.
"""

import math
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

from vectordb.config import (
    ATTENTION_DEFAULT_BUDGET,
    ATTENTION_FRESHNESS_HALF_LIFE,
    ATTENTION_MIN_SCORE,
    ATTENTION_WEIGHTS,
    CATEGORY_BOOSTS,
    COLLECTION_CONVERSATIONS,
    COLLECTION_DECISION_REGISTRY,
    COLLECTION_MESSAGES,
    COLLECTION_PATTERNS,
    COLLECTION_PRIMING_REGISTRY,
    COLLECTION_THREAD_REGISTRY,
    VECTOR_INDEX_NAME,
)
from vectordb.db import get_database
from vectordb.embeddings import embed_query


# ---------------------------------------------------------------------------
# Collection metadata: maps collection name -> (category, project_field, text_field)
# ---------------------------------------------------------------------------

_COLLECTION_META = {
    COLLECTION_DECISION_REGISTRY: ("decision", "project", "text"),
    COLLECTION_THREAD_REGISTRY: ("thread", "project", "title"),
    COLLECTION_PRIMING_REGISTRY: ("priming", "project", "content"),
    COLLECTION_PATTERNS: ("pattern", None, "content"),
    COLLECTION_CONVERSATIONS: ("conversation", "project_name", "summary"),
    COLLECTION_MESSAGES: ("message", "project_name", "text"),
}


# ---------------------------------------------------------------------------
# Attention scoring
# ---------------------------------------------------------------------------

def compute_attention(
    similarity,
    epistemic_tier=None,
    updated_at=None,
    has_conflicts=False,
    category="message",
):
    """Compute attention score for a single result.

    Args:
        similarity: Cosine similarity score from vector search (0-1).
        epistemic_tier: Epistemic confidence (0-1). Defaults to 0.5 if absent.
        updated_at: ISO 8601 timestamp string for freshness calculation.
        has_conflicts: Whether the item has active conflicts.
        category: Item category for category boost lookup.

    Returns:
        Float in [0.0, 1.0].
    """
    w = ATTENTION_WEIGHTS

    tier_score = epistemic_tier if epistemic_tier is not None else 0.5
    tier_score = max(0.0, min(1.0, tier_score))

    freshness = _compute_freshness(updated_at)
    conflict_bonus = 1.0 if has_conflicts else 0.0
    cat_boost = CATEGORY_BOOSTS.get(category, 0.0)

    score = (
        similarity * w["similarity"]
        + tier_score * w["epistemic_tier"]
        + freshness * w["freshness"]
        + conflict_bonus * w["conflict_salience"]
        + cat_boost * w["category_boost"]
    )

    return round(max(0.0, min(1.0, score)), 4)


def _compute_freshness(updated_at):
    """Exponential decay freshness score with configurable half-life.

    Returns 1.0 for items updated just now, decaying toward 0.0
    with a half-life of ATTENTION_FRESHNESS_HALF_LIFE days.
    """
    if not updated_at:
        return 0.5

    try:
        if isinstance(updated_at, str):
            dt = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
        elif isinstance(updated_at, datetime):
            dt = updated_at
        else:
            return 0.5

        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)

        age_days = (datetime.now(timezone.utc) - dt).total_seconds() / 86400
        if age_days < 0:
            return 1.0

        decay = math.exp(-0.693 * age_days / ATTENTION_FRESHNESS_HALF_LIFE)
        return round(decay, 4)
    except (ValueError, TypeError):
        return 0.5


# ---------------------------------------------------------------------------
# Single collection vector search
# ---------------------------------------------------------------------------

def _search_collection(collection_name, query_embedding, project, limit, min_sim, db):
    """$vectorSearch on a single collection. Returns results with metadata.

    Each result dict includes: text, source (collection name), category,
    similarity, plus any relevant metadata (uuid, local_id, epistemic_tier, etc).
    Strips _id and embedding fields.
    """
    meta = _COLLECTION_META.get(collection_name)
    if meta is None:
        return []

    category, project_field, text_field = meta

    vector_search_stage = {
        "$vectorSearch": {
            "index": VECTOR_INDEX_NAME,
            "path": "embedding",
            "queryVector": query_embedding,
            "numCandidates": limit * 10,
            "limit": limit,
        }
    }

    if project and project_field:
        search_filter = {project_field: project}
        if collection_name == COLLECTION_DECISION_REGISTRY:
            search_filter["status"] = "active"
        elif collection_name == COLLECTION_THREAD_REGISTRY:
            search_filter["status"] = {"$ne": "resolved"}
        elif collection_name == COLLECTION_PRIMING_REGISTRY:
            search_filter["status"] = "active"
        vector_search_stage["$vectorSearch"]["filter"] = search_filter

    pipeline = [
        vector_search_stage,
        {"$addFields": {"similarity": {"$meta": "vectorSearchScore"}}},
        {"$match": {"similarity": {"$gte": min_sim}}},
        {"$project": {"embedding": 0}},
    ]

    try:
        results = list(db[collection_name].aggregate(pipeline))
    except Exception:
        return []

    enriched = []
    for doc in results:
        doc_id = doc.pop("_id", None)
        text_value = doc.get(text_field, "")
        if isinstance(text_value, list):
            text_value = ", ".join(str(v) for v in text_value)

        enriched.append({
            "text": str(text_value)[:2000],
            "source": collection_name,
            "category": category,
            "similarity": doc.get("similarity", 0),
            "project": doc.get(project_field, "") if project_field else "",
            "uuid": doc.get("uuid", ""),
            "local_id": doc.get("local_id", ""),
            "epistemic_tier": doc.get("epistemic_tier"),
            "updated_at": doc.get("updated_at", ""),
            "has_conflicts": bool(doc.get("conflicts_with")),
            "status": doc.get("status", ""),
            "priority": doc.get("priority", ""),
            "pattern_type": doc.get("pattern_type", ""),
            "success_score": doc.get("success_score"),
        })

    return enriched


# ---------------------------------------------------------------------------
# Parallel search across collections
# ---------------------------------------------------------------------------

def _parallel_search(query_embedding, project, limit, min_sim, db):
    """Search 6 collections in parallel via ThreadPoolExecutor.

    Returns dict mapping collection_name -> list of result dicts.
    """
    collections = list(_COLLECTION_META.keys())
    results = {}

    with ThreadPoolExecutor(max_workers=6) as executor:
        future_to_col = {
            executor.submit(
                _search_collection, col, query_embedding, project, limit, min_sim, db
            ): col
            for col in collections
        }

        for future in as_completed(future_to_col):
            col = future_to_col[future]
            try:
                results[col] = future.result()
            except Exception:
                results[col] = []

    return results


# ---------------------------------------------------------------------------
# Budget-constrained text assembly
# ---------------------------------------------------------------------------

def _budget_trim(scored_results, budget):
    """Fill budget chars with highest-attention items.

    Args:
        scored_results: List of result dicts, each with 'attention' and 'text'.
        budget: Maximum total characters for the formatted text.

    Returns:
        Tuple of (trimmed_items, formatted_text).
    """
    sorted_results = sorted(scored_results, key=lambda r: r["attention"], reverse=True)

    included = []
    parts = []
    used = 0

    for result in sorted_results:
        text = result.get("text", "")
        source = result.get("source", "")
        category = result.get("category", "")
        attention = result.get("attention", 0)
        project = result.get("project", "")

        label = result.get("local_id") or result.get("uuid", "")[:8] or category
        line = f"[{category}|{attention:.2f}] {label}"
        if project:
            line += f" ({project})"
        line += f": {text[:500]}"

        line_len = len(line) + 1  # +1 for newline
        if used + line_len > budget:
            remaining = budget - used
            if remaining > 50:
                line = line[:remaining]
                parts.append(line)
                included.append(result)
            break

        parts.append(line)
        included.append(result)
        used += line_len

    formatted_text = "\n".join(parts)
    return included, formatted_text


# ---------------------------------------------------------------------------
# Entanglement enrichment
# ---------------------------------------------------------------------------

def enrich_with_entanglement(results, db=None):
    """Attach entanglement cluster data to results.

    Reads cached scan via get_latest_scan(). For each result whose UUID
    appears in a cluster, attaches cluster_id, cluster_projects,
    cluster_size, and avg_similarity.
    """
    if db is None:
        db = get_database()

    from vectordb.entanglement import get_latest_scan

    scan = get_latest_scan(db=db)
    if not scan or not scan.get("clusters"):
        return results

    uuid_to_cluster = {}
    for cluster in scan["clusters"]:
        cluster_info = {
            "cluster_id": cluster.get("cluster_id"),
            "cluster_projects": cluster.get("projects", []),
            "cluster_size": len(cluster.get("items", [])),
            "avg_similarity": cluster.get("avg_similarity", 0),
        }
        for item in cluster.get("items", []):
            uuid_to_cluster[item.get("uuid", "")] = cluster_info

    enriched = []
    for result in results:
        result_uuid = result.get("uuid", "")
        cluster_info = uuid_to_cluster.get(result_uuid)
        if cluster_info:
            enriched.append({**result, **cluster_info})
        else:
            enriched.append(result)

    return enriched


# ---------------------------------------------------------------------------
# Main recall function
# ---------------------------------------------------------------------------

def recall(
    query,
    project=None,
    budget=None,
    min_score=None,
    collections=None,
    db=None,
):
    """Cross-collection attention-weighted recall.

    1. Embed query once via embed_query()
    2. Search 6 collections in parallel (ThreadPoolExecutor)
    3. Score each result with compute_attention()
    4. Enrich with entanglement cluster data
    5. Budget-constrain: fill budget chars with highest-attention items
    6. Return structured context

    Args:
        query: Search query text.
        project: Optional project filter.
        budget: Max chars for context_text (default ATTENTION_DEFAULT_BUDGET).
        min_score: Minimum similarity threshold (default ATTENTION_MIN_SCORE).
        collections: Optional list of collection names to restrict search.
        db: Optional database instance.

    Returns:
        Dict with results, context_text, total_candidates, budget_used,
        collections_searched.
    """
    if db is None:
        db = get_database()
    if budget is None:
        budget = ATTENTION_DEFAULT_BUDGET
    if min_score is None:
        min_score = ATTENTION_MIN_SCORE

    query_embedding = embed_query(query)

    per_collection_results = _parallel_search(
        query_embedding, project, limit=10, min_sim=min_score, db=db,
    )

    if collections:
        per_collection_results = {
            k: v for k, v in per_collection_results.items()
            if k in collections
        }

    all_results = []
    for col_results in per_collection_results.values():
        all_results.extend(col_results)

    total_candidates = len(all_results)

    for result in all_results:
        result["attention"] = compute_attention(
            similarity=result.get("similarity", 0),
            epistemic_tier=result.get("epistemic_tier"),
            updated_at=result.get("updated_at"),
            has_conflicts=result.get("has_conflicts", False),
            category=result.get("category", "message"),
        )

    all_results = [r for r in all_results if r["attention"] >= min_score]

    all_results = enrich_with_entanglement(all_results, db=db)

    included, context_text = _budget_trim(all_results, budget)

    return {
        "results": included,
        "context_text": context_text,
        "total_candidates": total_candidates,
        "budget_used": len(context_text),
        "collections_searched": sorted(per_collection_results.keys()),
    }


# ---------------------------------------------------------------------------
# Project context assembly
# ---------------------------------------------------------------------------

def project_context(project, sections=None, db=None):
    """Full project state assembly.

    Gathers decisions, threads, flags, stale items, and conflict info
    for a single project.

    Args:
        project: Project display name.
        sections: Optional list of sections to include.
            Default: ["decisions", "threads", "flags", "stale", "conflicts"]
        db: Optional database instance.

    Returns:
        Dict keyed by section name.
    """
    if db is None:
        db = get_database()

    default_sections = ["decisions", "threads", "flags", "stale", "conflicts"]
    if sections is None:
        sections = default_sections

    from vectordb.decision_registry import get_active_decisions, get_stale_decisions
    from vectordb.thread_registry import get_active_threads, get_stale_threads
    from vectordb.expedition_flags import get_pending_flags

    result = {}

    if "decisions" in sections:
        decisions = get_active_decisions(project, db=db)
        result["decisions"] = [
            {k: v for k, v in d.items() if k != "embedding"}
            for d in decisions
        ]

    if "threads" in sections:
        threads = get_active_threads(project, db=db)
        result["threads"] = [
            {k: v for k, v in t.items() if k != "embedding"}
            for t in threads
        ]

    if "flags" in sections:
        result["flags"] = get_pending_flags(project, db=db)

    if "stale" in sections:
        stale_d = get_stale_decisions(project, db=db)
        stale_t = get_stale_threads(project, db=db)
        result["stale"] = {
            "decisions": [
                {k: v for k, v in d.items() if k != "embedding"}
                for d in stale_d
            ],
            "threads": [
                {k: v for k, v in t.items() if k != "embedding"}
                for t in stale_t
            ],
        }

    if "conflicts" in sections:
        conflict_docs = list(db[COLLECTION_DECISION_REGISTRY].find(
            {"project": project, "status": "active", "conflicts_with": {"$ne": []}},
            {"_id": 0, "embedding": 0},
        ))
        result["conflicts"] = conflict_docs

    return result


# ---------------------------------------------------------------------------
# One-call conversation bootstrap
# ---------------------------------------------------------------------------

def context_load(
    project,
    query=None,
    budget=None,
    db=None,
):
    """One-call conversation bootstrap: project state + optional query recall.

    Combines project_context() and recall() into a single call. The project
    state (decisions, threads, flags, stale, conflicts) is always included.
    If a query is provided, attention-weighted recall results fill the
    remaining budget.

    Args:
        project: Project display name.
        query: Optional search query for additional recall.
        budget: Max chars for the combined context_text (default 6000).
        db: Optional database instance.

    Returns:
        Dict with project state sections plus optional 'recall' key.
    """
    if db is None:
        db = get_database()
    if budget is None:
        budget = 6000

    ctx = project_context(project, db=db)

    if query:
        # Estimate project context size, reserve remaining budget for recall
        import json
        ctx_size = len(json.dumps(ctx, default=str))
        recall_budget = max(budget - ctx_size, 1000)

        recall_result = recall(
            query=query,
            project=project,
            budget=recall_budget,
            db=db,
        )
        ctx["recall"] = recall_result["results"]
        ctx["recall_context_text"] = recall_result["context_text"]
        ctx["recall_total_candidates"] = recall_result["total_candidates"]

    return ctx


# ---------------------------------------------------------------------------
# Alerts aggregation
# ---------------------------------------------------------------------------

def alerts(db=None):
    """Aggregate system-wide alerts.

    Returns counts and details for stale items, conflicts, pending flags,
    loose ends, and entanglement resonances.
    """
    if db is None:
        db = get_database()

    from vectordb.conversation_registry import list_projects
    from vectordb.decision_registry import get_stale_decisions
    from vectordb.thread_registry import get_stale_threads
    from vectordb.expedition_flags import get_pending_flags

    projects = list_projects(db=db)
    stale_decisions = []
    stale_threads = []
    total_pending_flags = 0

    for p in projects:
        name = p["project_name"]
        stale_decisions.extend(get_stale_decisions(name, db=db))
        stale_threads.extend(get_stale_threads(name, db=db))
        total_pending_flags += len(get_pending_flags(name, db=db))

    conflict_count = db[COLLECTION_DECISION_REGISTRY].count_documents(
        {"status": "active", "conflicts_with": {"$ne": []}}
    )

    from vectordb.entanglement import get_latest_scan
    latest_scan = get_latest_scan(db=db)
    loose_end_count = len(latest_scan.get("loose_ends", [])) if latest_scan else 0
    resonance_count = latest_scan.get("resonances_found", 0) if latest_scan else 0

    return {
        "stale_decisions": len(stale_decisions),
        "stale_threads": len(stale_threads),
        "conflicts": conflict_count,
        "pending_flags": total_pending_flags,
        "entanglement_resonances": resonance_count,
        "entanglement_loose_ends": loose_end_count,
    }
