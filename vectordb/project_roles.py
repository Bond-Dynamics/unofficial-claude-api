"""Forge OS Layer 3.5: GRAVITY — Project role assignments and lens configurations.

Manages the mapping between projects and their epistemic roles
in the gravity assist system. Roles define how a project's knowledge
bends the LLM's probability field.
"""

from datetime import datetime, timezone

from vectordb.config import (
    COLLECTION_LENS_CONFIGURATIONS,
    COLLECTION_PROJECT_ROLES,
)
from vectordb.db import get_database


ROLE_TYPES = {
    "connector": {
        "gravity_type": "lateral",
        "description": "Cross-domain bridges, isomorphisms, associations",
    },
    "navigator": {
        "gravity_type": "directional",
        "description": "Validated decisions, rejected alternatives, strategic direction",
    },
    "builder": {
        "gravity_type": "implementation",
        "description": "Technical patterns, architecture decisions, code approaches",
    },
    "evaluator": {
        "gravity_type": "quality",
        "description": "Quality scores, success/failure patterns",
    },
    "critic": {
        "gravity_type": "critical",
        "description": "Risks, conflicts, stale items, blind spots",
    },
    "compiler": {
        "gravity_type": "synthesis",
        "description": "Compiled expedition findings, priming blocks",
    },
}


# ---------------------------------------------------------------------------
# Project role CRUD
# ---------------------------------------------------------------------------

def assign_role(project_name, role, weight=1.0, description=None, db=None):
    """Assign an epistemic role to a project.

    Validates role is a known type. Upserts — one project can have
    only one role at a time.

    Args:
        project_name: Project display name.
        role: Role type (connector, navigator, builder, etc.).
        weight: Role weight 0.0-1.0 (default 1.0).
        description: Optional custom description override.
        db: Optional database instance.

    Returns:
        Dict with 'action' ("inserted" or "updated") and role details.
    """
    if db is None:
        db = get_database()

    if role not in ROLE_TYPES:
        return {"error": f"Unknown role '{role}'. Valid: {', '.join(ROLE_TYPES.keys())}"}

    from vectordb.conversation_registry import list_projects
    projects = list_projects(db=db)
    project_info = next(
        (p for p in projects if p["project_name"] == project_name), None
    )
    if project_info is None:
        return {"error": f"Project not found: {project_name}"}

    collection = db[COLLECTION_PROJECT_ROLES]
    now = datetime.now(timezone.utc).isoformat()
    role_meta = ROLE_TYPES[role]

    existing = collection.find_one({"project_name": project_name})

    doc = {
        "project_name": project_name,
        "project_uuid": project_info["project_uuid"],
        "role": role,
        "gravity_type": role_meta["gravity_type"],
        "description": description or role_meta["description"],
        "weight": max(0.0, min(1.0, weight)),
        "active": True,
        "updated_at": now,
    }

    if existing is not None:
        collection.update_one(
            {"project_name": project_name},
            {"$set": doc},
        )
        return {"action": "updated", **doc}

    doc["created_at"] = now
    collection.insert_one(doc)
    return {"action": "inserted", **{k: v for k, v in doc.items() if k != "_id"}}


def get_role(project_name, db=None):
    """Get the role assignment for a project.

    Returns:
        Role document or None.
    """
    if db is None:
        db = get_database()

    return db[COLLECTION_PROJECT_ROLES].find_one(
        {"project_name": project_name},
        {"_id": 0},
    )


def list_roles(active_only=True, db=None):
    """List all project role assignments.

    Args:
        active_only: If True, only return active roles.
        db: Optional database instance.

    Returns:
        List of role documents.
    """
    if db is None:
        db = get_database()

    query = {"active": True} if active_only else {}
    return list(
        db[COLLECTION_PROJECT_ROLES].find(query, {"_id": 0}).sort("role", 1)
    )


def remove_role(project_name, db=None):
    """Remove a project's role assignment.

    Returns:
        Dict with 'action' ("removed" or "not_found").
    """
    if db is None:
        db = get_database()

    result = db[COLLECTION_PROJECT_ROLES].delete_one(
        {"project_name": project_name}
    )

    if result.deleted_count > 0:
        return {"action": "removed", "project_name": project_name}
    return {"action": "not_found", "project_name": project_name}


# ---------------------------------------------------------------------------
# Lens configuration CRUD
# ---------------------------------------------------------------------------

def save_lens(lens_name, projects, description=None, default_budget=6000, db=None):
    """Save a named lens configuration.

    A lens is a reusable set of project-role assignments for
    orchestrated analysis.

    Args:
        lens_name: Unique name for this lens combo.
        projects: List of {project_name, role, weight?} dicts.
        description: Human-readable description.
        default_budget: Default budget in chars.
        db: Optional database instance.

    Returns:
        Dict with 'action' ("inserted" or "updated") and lens details.
    """
    if db is None:
        db = get_database()

    collection = db[COLLECTION_LENS_CONFIGURATIONS]
    now = datetime.now(timezone.utc).isoformat()

    normalized = []
    for p in projects:
        normalized.append({
            "project_name": p["project_name"],
            "role": p["role"],
            "weight": p.get("weight", 1.0),
        })

    existing = collection.find_one({"lens_name": lens_name})

    doc = {
        "lens_name": lens_name,
        "description": description or "",
        "projects": normalized,
        "default_budget": default_budget,
        "active": True,
        "updated_at": now,
    }

    if existing is not None:
        collection.update_one(
            {"lens_name": lens_name},
            {"$set": doc},
        )
        return {"action": "updated", **doc}

    doc["created_at"] = now
    collection.insert_one(doc)
    return {"action": "inserted", **{k: v for k, v in doc.items() if k != "_id"}}


def get_lens(lens_name, db=None):
    """Get a named lens configuration.

    Returns:
        Lens document or None.
    """
    if db is None:
        db = get_database()

    return db[COLLECTION_LENS_CONFIGURATIONS].find_one(
        {"lens_name": lens_name},
        {"_id": 0},
    )


def list_lenses(db=None):
    """List all saved lens configurations.

    Returns:
        List of lens documents.
    """
    if db is None:
        db = get_database()

    return list(
        db[COLLECTION_LENS_CONFIGURATIONS].find(
            {"active": True}, {"_id": 0}
        ).sort("lens_name", 1)
    )


def delete_lens(lens_name, db=None):
    """Delete a named lens configuration.

    Returns:
        Dict with 'action' ("deleted" or "not_found").
    """
    if db is None:
        db = get_database()

    result = db[COLLECTION_LENS_CONFIGURATIONS].delete_one(
        {"lens_name": lens_name}
    )

    if result.deleted_count > 0:
        return {"action": "deleted", "lens_name": lens_name}
    return {"action": "not_found", "lens_name": lens_name}
