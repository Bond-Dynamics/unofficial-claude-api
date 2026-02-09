"""Forge OS sync manifest loader and resolver.

Parses config/sync_manifest.yaml and resolves each target into a
fully-qualified sync plan with internal project names, data types,
filters, and merge strategy.
"""

from pathlib import Path
from typing import Optional

import yaml

from vectordb.conversation_registry import list_projects
from vectordb.db import get_database

DEFAULT_MANIFEST_PATH = (
    Path(__file__).resolve().parent.parent / "config" / "sync_manifest.yaml"
)


def load_manifest(path: Optional[str] = None) -> dict:
    """Parse the sync manifest YAML file.

    Args:
        path: Optional path override. Defaults to config/sync_manifest.yaml.

    Returns:
        Parsed manifest dict.

    Raises:
        FileNotFoundError: If the manifest file doesn't exist.
        ValueError: If the manifest version is unsupported.
    """
    manifest_path = Path(path) if path else DEFAULT_MANIFEST_PATH
    if not manifest_path.exists():
        raise FileNotFoundError(f"Sync manifest not found: {manifest_path}")

    with open(manifest_path) as f:
        manifest = yaml.safe_load(f)

    version = manifest.get("version", "")
    if version != "1":
        raise ValueError(f"Unsupported manifest version: {version!r} (expected '1')")

    return manifest


def get_internal_names(manifest: dict, claude_name: str) -> list[str]:
    """Resolve a Claude.ai project name to internal Forge OS project names.

    Uses the name_map from the manifest. If the mapping is ["*"], expands
    to all known projects from MongoDB via list_projects().

    Args:
        manifest: Parsed manifest dict.
        claude_name: The Claude.ai-facing project name.

    Returns:
        List of internal project name strings.
    """
    name_map = manifest.get("name_map", {})
    mapped = name_map.get(claude_name)

    if mapped is None:
        return [claude_name]

    if mapped == ["*"]:
        # Wildcard: collect names from conversation registry AND
        # decision/thread/flag registries (they use different names)
        names = set()
        for p in list_projects():
            names.add(p["project_name"])
        db = get_database()
        for col_name in ("decision_registry", "thread_registry", "expedition_flags"):
            for proj in db[col_name].distinct("project"):
                if proj:
                    names.add(proj)
        return sorted(names)

    return list(mapped)


def resolve_target(manifest: dict, project_uuid: str) -> Optional[dict]:
    """Merge defaults with target overrides for a single project UUID.

    Args:
        manifest: Parsed manifest dict.
        project_uuid: Claude.ai project UUID string.

    Returns:
        Resolved target dict, or None if the UUID isn't in the manifest.
    """
    targets = manifest.get("targets", {})
    target_config = targets.get(project_uuid)
    if target_config is None:
        return None

    defaults = manifest.get("defaults", {})
    claude_name = target_config.get("name", "")

    # Resolve enabled flag (default True)
    enabled = target_config.get("enabled", True)

    # Resolve data_types (target overrides defaults entirely if present)
    data_types = target_config.get("data_types", defaults.get("data_types", []))

    # Resolve filters (target keys override default keys)
    default_filters = dict(defaults.get("filters", {}))
    target_filters = target_config.get("filters", {})
    merged_filters = {**default_filters, **target_filters}

    # Resolve merge mode
    merge = target_config.get("merge", defaults.get("merge", False))

    # Resolve doc_prefix
    doc_prefix = target_config.get("doc_prefix", defaults.get("doc_prefix", "forge"))

    # Build internal names list from name_map + additional_sources
    internal_names = get_internal_names(manifest, claude_name)
    additional = target_config.get("additional_sources", [])
    for source in additional:
        if source not in internal_names:
            internal_names.append(source)

    return {
        "project_uuid": project_uuid,
        "claude_name": claude_name,
        "internal_names": internal_names,
        "data_types": list(data_types),
        "filters": merged_filters,
        "merge": merge,
        "doc_prefix": doc_prefix,
        "enabled": enabled,
    }


def resolve_all_targets(manifest: dict) -> list[dict]:
    """Resolve all enabled targets from the manifest.

    Args:
        manifest: Parsed manifest dict.

    Returns:
        List of resolved target dicts (enabled only).
    """
    targets = manifest.get("targets", {})
    resolved = []
    for project_uuid in targets:
        target = resolve_target(manifest, project_uuid)
        if target is not None and target["enabled"]:
            resolved.append(target)
    return resolved


def validate_manifest(manifest: dict) -> list[str]:
    """Validate a manifest and return warnings.

    Args:
        manifest: Parsed manifest dict.

    Returns:
        List of warning strings. Empty list means valid.
    """
    warnings = []

    if "version" not in manifest:
        warnings.append("Missing 'version' field")
    elif manifest["version"] != "1":
        warnings.append(f"Unsupported version: {manifest['version']}")

    if "targets" not in manifest:
        warnings.append("No 'targets' defined")
        return warnings

    valid_data_types = {"decisions", "threads", "flags", "conflicts", "lineage_summary"}
    targets = manifest.get("targets", {})

    for uuid_str, config in targets.items():
        prefix = f"Target {uuid_str}"

        if "name" not in config:
            warnings.append(f"{prefix}: missing 'name'")

        data_types = config.get(
            "data_types",
            manifest.get("defaults", {}).get("data_types", []),
        )
        unknown = set(data_types) - valid_data_types
        if unknown:
            warnings.append(f"{prefix}: unknown data_types: {unknown}")

        # Check name_map references
        name = config.get("name", "")
        name_map = manifest.get("name_map", {})
        if name and name not in name_map and config.get("enabled", True):
            warnings.append(
                f"{prefix} ({name}): not in name_map, will use name as-is"
            )

    return warnings
