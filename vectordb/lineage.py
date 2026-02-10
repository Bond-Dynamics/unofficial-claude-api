"""Forge OS Layer 2: GRAPH — Lineage edge graph.

Tracks compression-hop relationships between conversations.
Each edge records which decisions/threads were carried forward or
dropped during a compression event.
"""

from datetime import datetime, timezone

from vectordb.config import COLLECTION_LINEAGE_EDGES
from vectordb.db import get_database
from vectordb.events import emit_event
from vectordb.uuidv8 import lineage_id as derive_lineage_uuid


def add_edge(
    source_conversation,
    target_conversation,
    compression_tag=None,
    decisions_carried=None,
    decisions_dropped=None,
    threads_carried=None,
    threads_resolved=None,
    source_project=None,
    target_project=None,
    db=None,
):
    """Add or update a lineage edge between two conversations.

    Uses $addToSet for list fields so repeated syncs are idempotent.

    Args:
        source_conversation: UUID string of the compressed conversation.
        target_conversation: UUID string of the continuation conversation.
        compression_tag: Optional compression tag identifier.
        decisions_carried: List of decision UUIDs carried forward.
        decisions_dropped: List of decision UUIDs dropped.
        threads_carried: List of thread UUIDs carried forward.
        threads_resolved: List of thread UUIDs resolved.
        source_project: Project name of the source conversation.
        target_project: Project name of the target conversation.
        db: Optional database instance.

    Returns:
        Dict with 'action' ("inserted" or "updated") and 'edge_uuid'.
    """
    if db is None:
        db = get_database()

    collection = db[COLLECTION_LINEAGE_EDGES]
    now = datetime.now(timezone.utc)

    import uuid as uuid_mod
    edge_uuid = str(derive_lineage_uuid(
        uuid_mod.UUID(source_conversation),
        uuid_mod.UUID(target_conversation),
    ))

    existing = collection.find_one({"edge_uuid": edge_uuid})

    if existing is None:
        doc = {
            "edge_uuid": edge_uuid,
            "source_conversation": source_conversation,
            "target_conversation": target_conversation,
            "source_project": source_project or "",
            "target_project": target_project or "",
            "compression_tag": compression_tag or "",
            "decisions_carried": decisions_carried or [],
            "decisions_dropped": decisions_dropped or [],
            "threads_carried": threads_carried or [],
            "threads_resolved": threads_resolved or [],
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
        }
        collection.insert_one(doc)
        action = "inserted"
    else:
        update = {"$set": {"updated_at": now.isoformat()}}
        add_to_set = {}
        if decisions_carried:
            add_to_set["decisions_carried"] = {"$each": decisions_carried}
        if decisions_dropped:
            add_to_set["decisions_dropped"] = {"$each": decisions_dropped}
        if threads_carried:
            add_to_set["threads_carried"] = {"$each": threads_carried}
        if threads_resolved:
            add_to_set["threads_resolved"] = {"$each": threads_resolved}
        if add_to_set:
            update["$addToSet"] = add_to_set
        if compression_tag:
            update.setdefault("$set", {})["compression_tag"] = compression_tag
        if source_project:
            update.setdefault("$set", {})["source_project"] = source_project
        if target_project:
            update.setdefault("$set", {})["target_project"] = target_project

        collection.update_one({"edge_uuid": edge_uuid}, update)
        action = "updated"

    emit_event(
        "graph.lineage.edge",
        {
            "edge_uuid": edge_uuid,
            "source": source_conversation,
            "target": target_conversation,
            "action": action,
        },
        db=db,
    )

    return {"action": action, "edge_uuid": edge_uuid}


def get_ancestors(conversation_id, depth=5, db=None):
    """Walk backward through lineage to find ancestor conversations.

    Args:
        conversation_id: UUID string of the starting conversation.
        depth: Maximum number of hops backward.
        db: Optional database instance.

    Returns:
        List of edge documents from newest to oldest ancestor.
    """
    if db is None:
        db = get_database()

    collection = db[COLLECTION_LINEAGE_EDGES]
    ancestors = []
    current = conversation_id

    for _ in range(depth):
        edge = collection.find_one(
            {"target_conversation": current},
            {"_id": 0},
        )
        if edge is None:
            break
        ancestors.append(edge)
        current = edge["source_conversation"]

    return ancestors


def get_descendants(conversation_id, depth=5, db=None):
    """Walk forward through lineage to find descendant conversations.

    Args:
        conversation_id: UUID string of the starting conversation.
        depth: Maximum number of hops forward.
        db: Optional database instance.

    Returns:
        List of edge documents from oldest to newest descendant.
    """
    if db is None:
        db = get_database()

    collection = db[COLLECTION_LINEAGE_EDGES]
    descendants = []
    current = conversation_id

    for _ in range(depth):
        edge = collection.find_one(
            {"source_conversation": current},
            {"_id": 0},
        )
        if edge is None:
            break
        descendants.append(edge)
        current = edge["target_conversation"]

    return descendants


def get_lineage_chain(compression_tag, db=None):
    """Get all edges associated with a compression tag.

    Args:
        compression_tag: The compression tag to filter by.
        db: Optional database instance.

    Returns:
        List of edge documents for this compression event.
    """
    if db is None:
        db = get_database()

    collection = db[COLLECTION_LINEAGE_EDGES]
    return list(
        collection.find(
            {"compression_tag": compression_tag},
            {"_id": 0},
        ).sort("created_at", 1)
    )


def get_full_graph(project=None, db=None):
    """Get all lineage edges, optionally filtered by project.

    Args:
        project: Optional project name filter. Matches edges where
            either source_project or target_project equals the value.
        db: Optional database instance.

    Returns:
        List of all edge documents (without _id).
    """
    if db is None:
        db = get_database()

    collection = db[COLLECTION_LINEAGE_EDGES]
    query = {}
    if project:
        query = {
            "$or": [
                {"source_project": project},
                {"target_project": project},
            ]
        }

    return list(
        collection.find(query, {"_id": 0}).sort("created_at", 1)
    )


def trace_conversation(conversation_id, depth=10, db=None):
    """Build a full trace for a conversation: ancestors + descendants.

    Walks backward to find roots, then forward to find leaves,
    producing a complete lineage chain through the conversation.

    Args:
        conversation_id: UUID string of the starting conversation.
        depth: Maximum hops in each direction.
        db: Optional database instance.

    Returns:
        Dict with 'ancestors' (root-first), 'descendants' (oldest-first),
        'root' (earliest ancestor conversation ID),
        'leaves' (terminal descendant conversation IDs),
        'conversations' (set of all conversation IDs in the chain),
        'cross_project' (True if chain spans multiple projects).
    """
    ancestors = get_ancestors(conversation_id, depth=depth, db=db)
    descendants = get_descendants(conversation_id, depth=depth, db=db)

    root = conversation_id
    if ancestors:
        root = ancestors[-1]["source_conversation"]

    leaves = [conversation_id]
    if descendants:
        leaves = [descendants[-1]["target_conversation"]]

    all_conversations = {conversation_id}
    all_projects = set()
    for edge in ancestors:
        all_conversations.add(edge["source_conversation"])
        all_conversations.add(edge["target_conversation"])
        if edge.get("source_project"):
            all_projects.add(edge["source_project"])
        if edge.get("target_project"):
            all_projects.add(edge["target_project"])

    for edge in descendants:
        all_conversations.add(edge["source_conversation"])
        all_conversations.add(edge["target_conversation"])
        if edge.get("source_project"):
            all_projects.add(edge["source_project"])
        if edge.get("target_project"):
            all_projects.add(edge["target_project"])

    all_projects.discard("")

    return {
        "ancestors": list(reversed(ancestors)),
        "descendants": descendants,
        "root": root,
        "leaves": leaves,
        "conversations": all_conversations,
        "projects": all_projects,
        "cross_project": len(all_projects) > 1,
    }
