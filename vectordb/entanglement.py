"""Forge OS Layer 2: GRAPH — Cross-project entanglement discovery.

Scans decisions, threads, and lineage edges across all projects to find
semantic resonances, bridge points, and loose ends. Uses Union-Find
clustering to group related items into entanglement clusters.

Similarity tiers:
  - strong: >= 0.65 (high semantic overlap across projects)
  - weak:   >= 0.50 (thematic connection worth noting)

Existing conflict detection (conflicts.py) handles >= 0.85 within a
single project. This module operates at lower thresholds across projects.
"""

from datetime import datetime, timezone

import uuid as uuid_mod

from vectordb.blob_store import store_json as blob_store_json
from vectordb.config import (
    COLLECTION_DECISION_REGISTRY,
    COLLECTION_ENTANGLEMENT_SCANS,
    COLLECTION_THREAD_REGISTRY,
    EMBEDDING_DIMENSIONS,
    ENTANGLEMENT_STRONG_THRESHOLD,
    ENTANGLEMENT_WEAK_THRESHOLD,
    VECTOR_INDEX_NAME,
)
from vectordb.conversation_registry import list_projects
from vectordb.db import get_database
from vectordb.embeddings import embed_texts
from vectordb.lineage import get_full_graph


# ---------------------------------------------------------------------------
# Thread embedding backfill
# ---------------------------------------------------------------------------

def ensure_thread_embeddings(db=None):
    """Embed any threads missing the 'embedding' field.

    Fetches all threads without an embedding, batch-embeds their titles
    via VoyageAI, and stores the vectors back into MongoDB.

    Args:
        db: Optional database instance.

    Returns:
        Number of threads embedded.
    """
    if db is None:
        db = get_database()

    collection = db[COLLECTION_THREAD_REGISTRY]
    missing = list(collection.find(
        {"embedding": {"$exists": False}},
        {"_id": 0, "uuid": 1, "title": 1},
    ))

    if not missing:
        return 0

    titles = [t.get("title", "")[:8000] for t in missing]
    try:
        embeddings = embed_texts(titles)
    except Exception:
        return 0

    count = 0
    for doc, embedding in zip(missing, embeddings):
        collection.update_one(
            {"uuid": doc["uuid"]},
            {"$set": {"embedding": embedding}},
        )
        count += 1

    return count


# ---------------------------------------------------------------------------
# Cross-project vector search helpers
# ---------------------------------------------------------------------------

def _classify_tier(similarity):
    """Classify a similarity score into a tier label."""
    if similarity >= ENTANGLEMENT_STRONG_THRESHOLD:
        return "strong"
    return "weak"


def _vector_search_cross_project(
    collection, query_vector, source_project, limit=10, min_similarity=None,
):
    """Run $vectorSearch excluding the source project.

    Args:
        collection: MongoDB collection with a vector_index.
        query_vector: 1024-dim embedding vector.
        source_project: Project name to exclude from results.
        limit: Max results.
        min_similarity: Minimum similarity threshold.

    Returns:
        List of result dicts with 'similarity' field added.
    """
    if min_similarity is None:
        min_similarity = ENTANGLEMENT_WEAK_THRESHOLD

    pipeline = [
        {
            "$vectorSearch": {
                "index": VECTOR_INDEX_NAME,
                "path": "embedding",
                "queryVector": query_vector,
                "numCandidates": limit * 10,
                "limit": limit,
                "filter": {"project": {"$ne": source_project}},
            }
        },
        {"$addFields": {"similarity": {"$meta": "vectorSearchScore"}}},
        {"$project": {"embedding": 0}},
    ]

    results = list(collection.aggregate(pipeline))
    return [r for r in results if r.get("similarity", 0) >= min_similarity]


def _vector_search_global(
    collection, query_vector, limit=10, min_similarity=None,
):
    """Run $vectorSearch across all projects (no project filter).

    Args:
        collection: MongoDB collection with a vector_index.
        query_vector: 1024-dim embedding vector.
        limit: Max results.
        min_similarity: Minimum similarity threshold.

    Returns:
        List of result dicts with 'similarity' field added.
    """
    if min_similarity is None:
        min_similarity = ENTANGLEMENT_WEAK_THRESHOLD

    pipeline = [
        {
            "$vectorSearch": {
                "index": VECTOR_INDEX_NAME,
                "path": "embedding",
                "queryVector": query_vector,
                "numCandidates": limit * 10,
                "limit": limit,
            }
        },
        {"$addFields": {"similarity": {"$meta": "vectorSearchScore"}}},
        {"$project": {"embedding": 0}},
    ]

    results = list(collection.aggregate(pipeline))
    return [r for r in results if r.get("similarity", 0) >= min_similarity]


# ---------------------------------------------------------------------------
# Cross-project resonance finders
# ---------------------------------------------------------------------------

def find_cross_project_decision_resonances(min_similarity=None, db=None):
    """For each project's decisions, search decision_registry excluding same project.

    Returns list of resonance dicts:
        {source_uuid, target_uuid, source_type, target_type,
         source_project, target_project, similarity, tier}
    """
    if min_similarity is None:
        min_similarity = ENTANGLEMENT_WEAK_THRESHOLD
    if db is None:
        db = get_database()

    collection = db[COLLECTION_DECISION_REGISTRY]
    projects = list_projects(db=db)
    resonances = []
    seen_pairs = set()

    for proj in projects:
        name = proj["project_name"]
        decisions = list(collection.find(
            {"project": name, "status": "active", "embedding": {"$exists": True}},
            {"_id": 0, "uuid": 1, "local_id": 1, "text": 1, "project": 1, "embedding": 1},
        ))

        for d in decisions:
            embedding = d.get("embedding")
            if not embedding:
                continue

            matches = _vector_search_cross_project(
                collection, embedding, name,
                limit=5, min_similarity=min_similarity,
            )

            for m in matches:
                pair = tuple(sorted([d["uuid"], m["uuid"]]))
                if pair in seen_pairs:
                    continue
                seen_pairs.add(pair)

                resonances.append({
                    "source_uuid": d["uuid"],
                    "target_uuid": m["uuid"],
                    "source_type": "decision",
                    "target_type": "decision",
                    "source_project": name,
                    "target_project": m.get("project", ""),
                    "source_local_id": d.get("local_id", ""),
                    "target_local_id": m.get("local_id", ""),
                    "source_text": d.get("text", "")[:200],
                    "target_text": m.get("text", "")[:200],
                    "similarity": round(m["similarity"], 4),
                    "tier": _classify_tier(m["similarity"]),
                })

    return resonances


def find_decision_thread_resonances(min_similarity=None, db=None):
    """For each decision embedding, search thread_registry globally.

    Finds decision-thread resonances across the full graph.

    Returns list of resonance dicts.
    """
    if min_similarity is None:
        min_similarity = ENTANGLEMENT_WEAK_THRESHOLD
    if db is None:
        db = get_database()

    decision_col = db[COLLECTION_DECISION_REGISTRY]
    thread_col = db[COLLECTION_THREAD_REGISTRY]
    projects = list_projects(db=db)
    resonances = []
    seen_pairs = set()

    for proj in projects:
        name = proj["project_name"]
        decisions = list(decision_col.find(
            {"project": name, "status": "active", "embedding": {"$exists": True}},
            {"_id": 0, "uuid": 1, "local_id": 1, "text": 1, "project": 1, "embedding": 1},
        ))

        for d in decisions:
            embedding = d.get("embedding")
            if not embedding:
                continue

            matches = _vector_search_global(
                thread_col, embedding,
                limit=5, min_similarity=min_similarity,
            )

            for m in matches:
                if d.get("project") == m.get("project"):
                    continue
                pair = tuple(sorted([d["uuid"], m["uuid"]]))
                if pair in seen_pairs:
                    continue
                seen_pairs.add(pair)

                resonances.append({
                    "source_uuid": d["uuid"],
                    "target_uuid": m["uuid"],
                    "source_type": "decision",
                    "target_type": "thread",
                    "source_project": name,
                    "target_project": m.get("project", ""),
                    "source_local_id": d.get("local_id", ""),
                    "target_local_id": m.get("local_id", ""),
                    "source_text": d.get("text", "")[:200],
                    "target_text": m.get("title", "")[:200],
                    "similarity": round(m["similarity"], 4),
                    "tier": _classify_tier(m["similarity"]),
                })

    return resonances


def find_cross_project_thread_resonances(min_similarity=None, db=None):
    """For each thread embedding, search thread_registry excluding same project.

    Returns list of resonance dicts.
    """
    if min_similarity is None:
        min_similarity = ENTANGLEMENT_WEAK_THRESHOLD
    if db is None:
        db = get_database()

    collection = db[COLLECTION_THREAD_REGISTRY]
    projects = list_projects(db=db)
    resonances = []
    seen_pairs = set()

    for proj in projects:
        name = proj["project_name"]
        threads = list(collection.find(
            {"project": name, "status": {"$ne": "resolved"}, "embedding": {"$exists": True}},
            {"_id": 0, "uuid": 1, "local_id": 1, "title": 1, "project": 1, "embedding": 1},
        ))

        for t in threads:
            embedding = t.get("embedding")
            if not embedding:
                continue

            matches = _vector_search_cross_project(
                collection, embedding, name,
                limit=5, min_similarity=min_similarity,
            )

            for m in matches:
                pair = tuple(sorted([t["uuid"], m["uuid"]]))
                if pair in seen_pairs:
                    continue
                seen_pairs.add(pair)

                resonances.append({
                    "source_uuid": t["uuid"],
                    "target_uuid": m["uuid"],
                    "source_type": "thread",
                    "target_type": "thread",
                    "source_project": name,
                    "target_project": m.get("project", ""),
                    "source_local_id": t.get("local_id", ""),
                    "target_local_id": m.get("local_id", ""),
                    "source_text": t.get("title", "")[:200],
                    "target_text": m.get("title", "")[:200],
                    "similarity": round(m["similarity"], 4),
                    "tier": _classify_tier(m["similarity"]),
                })

    return resonances


# ---------------------------------------------------------------------------
# Lineage bridge detection
# ---------------------------------------------------------------------------

def find_lineage_bridges(db=None):
    """Find decisions/threads appearing in lineage chains across multiple projects.

    Scans lineage_edges for decisions_carried / threads_carried that appear
    in edges with different source_project / target_project.

    Returns:
        List of bridge dicts: {uuid, type, projects, edge_count}.
    """
    edges = get_full_graph(db=db)

    uuid_projects = {}
    uuid_edges = {}

    for edge in edges:
        src_proj = edge.get("source_project", "")
        tgt_proj = edge.get("target_project", "")
        edge_projects = {p for p in [src_proj, tgt_proj] if p}

        for d_uuid in edge.get("decisions_carried", []):
            uuid_projects.setdefault(d_uuid, {"type": "decision", "projects": set(), "edge_count": 0})
            uuid_projects[d_uuid]["projects"].update(edge_projects)
            uuid_projects[d_uuid]["edge_count"] += 1

        for t_uuid in edge.get("threads_carried", []):
            uuid_projects.setdefault(t_uuid, {"type": "thread", "projects": set(), "edge_count": 0})
            uuid_projects[t_uuid]["projects"].update(edge_projects)
            uuid_projects[t_uuid]["edge_count"] += 1

    bridges = []
    for uuid, info in uuid_projects.items():
        if len(info["projects"]) > 1:
            bridges.append({
                "uuid": uuid,
                "type": info["type"],
                "projects": sorted(info["projects"]),
                "edge_count": info["edge_count"],
            })

    bridges.sort(key=lambda b: b["edge_count"], reverse=True)
    return bridges


# ---------------------------------------------------------------------------
# Union-Find clustering
# ---------------------------------------------------------------------------

class _UnionFind:
    """Simple Union-Find with path compression and union by rank."""

    def __init__(self):
        self._parent = {}
        self._rank = {}

    def find(self, x):
        if x not in self._parent:
            self._parent[x] = x
            self._rank[x] = 0
        if self._parent[x] != x:
            self._parent[x] = self.find(self._parent[x])
        return self._parent[x]

    def union(self, x, y):
        rx, ry = self.find(x), self.find(y)
        if rx == ry:
            return
        if self._rank[rx] < self._rank[ry]:
            rx, ry = ry, rx
        self._parent[ry] = rx
        if self._rank[rx] == self._rank[ry]:
            self._rank[rx] += 1


def _cluster_resonances(resonances, all_items_by_uuid):
    """Group resonant items into clusters using Union-Find.

    Args:
        resonances: List of resonance dicts with source_uuid and target_uuid.
        all_items_by_uuid: Dict mapping uuid -> {type, project, local_id, text/title}.

    Returns:
        List of cluster dicts with items, projects, resonances, avg_similarity,
        strongest_link.
    """
    if not resonances:
        return []

    uf = _UnionFind()
    for r in resonances:
        uf.union(r["source_uuid"], r["target_uuid"])

    groups = {}
    for r in resonances:
        root = uf.find(r["source_uuid"])
        groups.setdefault(root, {"uuids": set(), "resonances": []})
        groups[root]["uuids"].add(r["source_uuid"])
        groups[root]["uuids"].add(r["target_uuid"])
        groups[root]["resonances"].append(r)

    clusters = []
    for cluster_id, (root, group) in enumerate(sorted(groups.items()), 1):
        items = []
        projects = set()
        for uuid in sorted(group["uuids"]):
            info = all_items_by_uuid.get(uuid, {})
            items.append({
                "uuid": uuid,
                "type": info.get("type", "unknown"),
                "project": info.get("project", ""),
                "local_id": info.get("local_id", ""),
                "text": info.get("text", ""),
            })
            if info.get("project"):
                projects.add(info["project"])

        cluster_resonances = [
            {
                "from": r["source_uuid"],
                "to": r["target_uuid"],
                "similarity": r["similarity"],
                "tier": r["tier"],
            }
            for r in group["resonances"]
        ]

        similarities = [r["similarity"] for r in group["resonances"]]
        avg_sim = sum(similarities) / len(similarities) if similarities else 0
        strongest = max(group["resonances"], key=lambda r: r["similarity"])

        clusters.append({
            "cluster_id": cluster_id,
            "items": items,
            "projects": sorted(projects),
            "resonances": cluster_resonances,
            "avg_similarity": round(avg_sim, 4),
            "strongest_link": {
                "from": strongest["source_uuid"],
                "to": strongest["target_uuid"],
                "similarity": strongest["similarity"],
            },
        })

    clusters.sort(key=lambda c: c["avg_similarity"], reverse=True)
    return clusters


# ---------------------------------------------------------------------------
# Loose end detection
# ---------------------------------------------------------------------------

def _find_loose_ends(all_items_by_uuid, clustered_uuids, db=None):
    """Find items with zero cross-project resonances.

    Args:
        all_items_by_uuid: Dict of all scanned items by uuid.
        clustered_uuids: Set of uuids that appear in at least one cluster.
        db: Optional database instance.

    Returns:
        List of loose end dicts.
    """
    loose_ends = []
    for uuid, info in sorted(all_items_by_uuid.items()):
        if uuid in clustered_uuids:
            continue
        loose_ends.append({
            "uuid": uuid,
            "type": info.get("type", "unknown"),
            "project": info.get("project", ""),
            "local_id": info.get("local_id", ""),
            "text": info.get("text", ""),
        })

    return loose_ends


# ---------------------------------------------------------------------------
# Build items index for clustering
# ---------------------------------------------------------------------------

def _build_items_index(db):
    """Build a uuid -> item info dict for all active decisions and threads."""
    items = {}

    decisions = list(db[COLLECTION_DECISION_REGISTRY].find(
        {"status": "active"},
        {"_id": 0, "uuid": 1, "local_id": 1, "text": 1, "project": 1},
    ))
    for d in decisions:
        items[d["uuid"]] = {
            "type": "decision",
            "project": d.get("project", ""),
            "local_id": d.get("local_id", ""),
            "text": d.get("text", "")[:200],
        }

    threads = list(db[COLLECTION_THREAD_REGISTRY].find(
        {"status": {"$ne": "resolved"}},
        {"_id": 0, "uuid": 1, "local_id": 1, "title": 1, "project": 1},
    ))
    for t in threads:
        items[t["uuid"]] = {
            "type": "thread",
            "project": t.get("project", ""),
            "local_id": t.get("local_id", ""),
            "text": t.get("title", "")[:200],
        }

    return items


# ---------------------------------------------------------------------------
# Main scan orchestrators
# ---------------------------------------------------------------------------

def scan(min_similarity=None, db=None):
    """Full entanglement scan across all projects.

    Steps:
        1. Backfill thread embeddings
        2. Find cross-project decision resonances
        3. Find decision-thread resonances
        4. Find cross-project thread resonances
        5. Detect lineage bridges
        6. Cluster all resonances via Union-Find
        7. Find loose ends

    Args:
        min_similarity: Override minimum similarity threshold.
        db: Optional database instance.

    Returns:
        Scan result dict with clusters, bridges, loose_ends, stats.
    """
    if min_similarity is None:
        min_similarity = ENTANGLEMENT_WEAK_THRESHOLD
    if db is None:
        db = get_database()

    threads_embedded = ensure_thread_embeddings(db=db)

    all_items = _build_items_index(db)
    decisions_count = sum(1 for v in all_items.values() if v["type"] == "decision")
    threads_count = sum(1 for v in all_items.values() if v["type"] == "thread")

    resonances = []
    resonances.extend(find_cross_project_decision_resonances(min_similarity, db=db))
    resonances.extend(find_decision_thread_resonances(min_similarity, db=db))
    resonances.extend(find_cross_project_thread_resonances(min_similarity, db=db))

    bridges = find_lineage_bridges(db=db)

    clusters = _cluster_resonances(resonances, all_items)
    clustered_uuids = set()
    for c in clusters:
        for item in c["items"]:
            clustered_uuids.add(item["uuid"])

    loose_ends = _find_loose_ends(all_items, clustered_uuids, db=db)

    strong_count = sum(1 for r in resonances if r["tier"] == "strong")
    weak_count = sum(1 for r in resonances if r["tier"] == "weak")

    return {
        "scanned_at": datetime.now(timezone.utc).isoformat(),
        "decisions_scanned": decisions_count,
        "threads_scanned": threads_count,
        "threads_embedded": threads_embedded,
        "resonances_found": len(resonances),
        "clusters": clusters,
        "bridges": bridges,
        "loose_ends": loose_ends,
        "by_tier": {"strong": strong_count, "weak": weak_count},
    }


def scan_project(project_name, min_similarity=None, db=None):
    """Scan centered on one project's items.

    Finds resonances where the source OR target belongs to the specified
    project, then clusters and reports only those.

    Args:
        project_name: Project display name to center the scan on.
        min_similarity: Override minimum similarity threshold.
        db: Optional database instance.

    Returns:
        Scan result dict filtered to the specified project.
    """
    full_result = scan(min_similarity=min_similarity, db=db)

    project_clusters = [
        c for c in full_result["clusters"]
        if project_name in c["projects"]
    ]

    project_bridges = [
        b for b in full_result["bridges"]
        if project_name in b["projects"]
    ]

    project_loose_ends = [
        le for le in full_result["loose_ends"]
        if le["project"] == project_name
    ]

    project_resonance_count = 0
    strong = 0
    weak = 0
    for c in project_clusters:
        for r in c["resonances"]:
            project_resonance_count += 1
            if r["tier"] == "strong":
                strong += 1
            else:
                weak += 1

    return {
        "scanned_at": full_result["scanned_at"],
        "project": project_name,
        "decisions_scanned": full_result["decisions_scanned"],
        "threads_scanned": full_result["threads_scanned"],
        "threads_embedded": full_result["threads_embedded"],
        "resonances_found": project_resonance_count,
        "clusters": project_clusters,
        "bridges": project_bridges,
        "loose_ends": project_loose_ends,
        "by_tier": {"strong": strong, "weak": weak},
    }


# ---------------------------------------------------------------------------
# Scan persistence — store / retrieve cached scan results
# ---------------------------------------------------------------------------

def save_scan(result, db=None):
    """Persist a scan result to the entanglement_scans collection.

    Adds a unique scan_id and stores the full result. Previous scans
    are kept for history.

    Args:
        result: Scan result dict from scan() or scan_project().
        db: Optional database instance.

    Returns:
        The scan_id string assigned to this scan.
    """
    if db is None:
        db = get_database()

    collection = db[COLLECTION_ENTANGLEMENT_SCANS]
    scan_id = str(uuid_mod.uuid4())

    doc = {**result, "scan_id": scan_id}
    if result.get("min_similarity") is not None:
        doc["min_similarity"] = result["min_similarity"]
    if result.get("project") is None:
        doc.pop("project", None)

    clusters_ref = blob_store_json(doc.get("clusters"))
    bridges_ref = blob_store_json(doc.get("bridges"))
    loose_ends_ref = blob_store_json(doc.get("loose_ends"))
    if clusters_ref:
        doc["clusters_blob_ref"] = clusters_ref
    if bridges_ref:
        doc["bridges_blob_ref"] = bridges_ref
    if loose_ends_ref:
        doc["loose_ends_blob_ref"] = loose_ends_ref

    collection.insert_one(doc)
    return scan_id


def get_latest_scan(project=None, db=None):
    """Retrieve the most recent scan result from the cache.

    Args:
        project: If set, fetch the latest project-scoped scan.
            If None, fetch the latest full scan (where project is absent).
        db: Optional database instance.

    Returns:
        Scan result dict with scan_id, or None if no cached scan exists.
    """
    if db is None:
        db = get_database()

    collection = db[COLLECTION_ENTANGLEMENT_SCANS]

    if project:
        query = {"project": project}
    else:
        query = {"$or": [
            {"project": {"$exists": False}},
            {"project": None},
        ]}

    doc = collection.find_one(
        query, {"_id": 0}, sort=[("scanned_at", -1)]
    )
    return doc


def list_scans(limit=20, db=None):
    """List recent scan summaries (without full cluster/bridge/loose_end data).

    Args:
        limit: Max number of scans to return.
        db: Optional database instance.

    Returns:
        List of scan summary dicts.
    """
    if db is None:
        db = get_database()

    collection = db[COLLECTION_ENTANGLEMENT_SCANS]

    docs = list(collection.find(
        {},
        {
            "_id": 0,
            "scan_id": 1,
            "scanned_at": 1,
            "project": 1,
            "decisions_scanned": 1,
            "threads_scanned": 1,
            "resonances_found": 1,
            "by_tier": 1,
            "min_similarity": 1,
        },
    ).sort("scanned_at", -1).limit(limit))

    for doc in docs:
        doc["cluster_count"] = 0
        doc["bridge_count"] = 0
        doc["loose_end_count"] = 0

    full_docs = list(collection.find(
        {"scan_id": {"$in": [d["scan_id"] for d in docs]}},
        {"_id": 0, "scan_id": 1, "clusters": 1, "bridges": 1, "loose_ends": 1},
    ))
    counts_by_id = {
        d["scan_id"]: {
            "cluster_count": len(d.get("clusters", [])),
            "bridge_count": len(d.get("bridges", [])),
            "loose_end_count": len(d.get("loose_ends", [])),
        }
        for d in full_docs
    }
    for doc in docs:
        counts = counts_by_id.get(doc["scan_id"], {})
        doc["cluster_count"] = counts.get("cluster_count", 0)
        doc["bridge_count"] = counts.get("bridge_count", 0)
        doc["loose_end_count"] = counts.get("loose_end_count", 0)

    return docs


def get_scan(scan_id, db=None):
    """Retrieve a specific scan by its scan_id.

    Args:
        scan_id: The unique scan identifier.
        db: Optional database instance.

    Returns:
        Full scan result dict, or None if not found.
    """
    if db is None:
        db = get_database()

    return db[COLLECTION_ENTANGLEMENT_SCANS].find_one(
        {"scan_id": scan_id}, {"_id": 0}
    )


def scan_and_save(min_similarity=None, db=None):
    """Run a full scan and persist the result.

    Convenience wrapper that calls scan() then save_scan().

    Args:
        min_similarity: Override minimum similarity threshold.
        db: Optional database instance.

    Returns:
        Scan result dict with scan_id included.
    """
    if db is None:
        db = get_database()

    result = scan(min_similarity=min_similarity, db=db)
    if min_similarity is not None:
        result["min_similarity"] = min_similarity
    scan_id = save_scan(result, db=db)
    return {**result, "scan_id": scan_id}


def scan_project_and_save(project_name, min_similarity=None, db=None):
    """Run a project-scoped scan and persist the result.

    Args:
        project_name: Project display name.
        min_similarity: Override minimum similarity threshold.
        db: Optional database instance.

    Returns:
        Scan result dict with scan_id included.
    """
    if db is None:
        db = get_database()

    result = scan_project(project_name, min_similarity=min_similarity, db=db)
    if min_similarity is not None:
        result["min_similarity"] = min_similarity
    scan_id = save_scan(result, db=db)
    return {**result, "scan_id": scan_id}
