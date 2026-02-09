"""Forge OS sync engine — compile MongoDB state to markdown and push to Claude.ai.

Compilers query MongoDB registries and produce markdown documents.
The orchestrator pushes compiled docs to Claude.ai projects via the
write-back API, guided by the sync manifest.
"""

import time
from datetime import datetime, timezone
from typing import Optional

from vectordb.claude_api import ClaudeSession, get_session
from vectordb.conversation_registry import list_projects
from vectordb.db import get_database
from vectordb.decision_registry import get_active_decisions
from vectordb.expedition_flags import get_pending_flags, get_flags_by_category
from vectordb.lineage import get_full_graph
from vectordb.sync_manifest import load_manifest, resolve_all_targets, resolve_target
from vectordb.thread_registry import get_active_threads


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _passes_filters(item: dict, filters: dict) -> bool:
    """Check whether a single item passes the manifest filters."""
    min_tier = filters.get("min_tier")
    if min_tier is not None:
        tier = item.get("epistemic_tier")
        if tier is None or tier < min_tier:
            return False

    max_hops = filters.get("max_hops")
    if max_hops is not None:
        hops = item.get("hops_since_validated", 0)
        if hops > max_hops:
            return False

    return True


def _status_matches(item_status: str, filter_spec: Optional[str]) -> bool:
    """Check if an item's status matches a filter spec.

    Specs: "active" (exact match), "!resolved" (not resolved), None (any).
    """
    if filter_spec is None:
        return True
    if filter_spec.startswith("!"):
        return item_status != filter_spec[1:]
    return item_status == filter_spec


# ---------------------------------------------------------------------------
# Compilers: MongoDB → markdown docs
# ---------------------------------------------------------------------------

def compile_decisions(
    internal_names: list[str],
    filters: dict,
    merge: bool,
    doc_prefix: str,
) -> list[dict]:
    """Compile active decisions into markdown doc(s).

    Args:
        internal_names: Forge OS project names to pull from.
        filters: Filter dict from resolved manifest target.
        merge: If True, merge all projects into one doc.
        doc_prefix: Filename prefix (e.g. "forge").

    Returns:
        List of dicts with file_name, content, item_count.
    """
    status_filter = filters.get("decisions_status", "active")
    all_decisions = []

    for name in internal_names:
        decisions = get_active_decisions(name)
        for d in decisions:
            if not _passes_filters(d, filters):
                continue
            if not _status_matches(d.get("status", "active"), status_filter):
                continue
            all_decisions.append({**d, "_source_project": name})

    if not all_decisions:
        return []

    if merge:
        return [_build_merged_decisions_doc(all_decisions, doc_prefix)]

    return _build_per_project_decisions_docs(all_decisions, internal_names, doc_prefix)


def _build_merged_decisions_doc(
    decisions: list[dict], doc_prefix: str
) -> dict:
    lines = [f"# Active Decisions — All Projects\n"]
    lines.append(f"_Auto-synced from Forge OS. {len(decisions)} decisions. {_timestamp()}_\n")

    by_project: dict[str, list[dict]] = {}
    for d in decisions:
        proj = d.get("_source_project", "Unknown")
        by_project.setdefault(proj, []).append(d)

    for proj in sorted(by_project):
        proj_decisions = sorted(by_project[proj], key=lambda x: x.get("local_id", ""))
        lines.append(f"\n## {proj}\n")
        for d in proj_decisions:
            lines.extend(_format_decision(d))

    return {
        "file_name": f"{doc_prefix}_decisions_all.md",
        "content": "\n".join(lines),
        "item_count": len(decisions),
    }


def _build_per_project_decisions_docs(
    decisions: list[dict],
    internal_names: list[str],
    doc_prefix: str,
) -> list[dict]:
    by_project: dict[str, list[dict]] = {}
    for d in decisions:
        proj = d.get("_source_project", "Unknown")
        by_project.setdefault(proj, []).append(d)

    docs = []
    for name in internal_names:
        proj_decisions = by_project.get(name, [])
        if not proj_decisions:
            continue
        proj_decisions.sort(key=lambda x: x.get("local_id", ""))
        lines = [f"# Active Decisions — {name}\n"]
        lines.append(
            f"_Auto-synced from Forge OS. {len(proj_decisions)} decisions. {_timestamp()}_\n"
        )
        for d in proj_decisions:
            lines.extend(_format_decision(d))

        safe_name = name.replace(" ", "_").replace("/", "_")
        docs.append({
            "file_name": f"{doc_prefix}_decisions_{safe_name}.md",
            "content": "\n".join(lines),
            "item_count": len(proj_decisions),
        })

    return docs


def _format_decision(d: dict) -> list[str]:
    local_id = d.get("local_id", "?")
    text = d.get("text", "")
    tier = d.get("epistemic_tier", "?")
    status = d.get("status", "active")
    rationale = d.get("rationale", "")
    hops = d.get("hops_since_validated", 0)
    conflicts = d.get("conflicts_with", [])

    lines = [f"### {local_id}: {text}\n"]
    lines.append(f"- **Tier:** {tier}")
    lines.append(f"- **Status:** {status}")
    lines.append(f"- **Hops since validated:** {hops}")
    if rationale:
        lines.append(f"- **Rationale:** {rationale}")
    if conflicts:
        lines.append(f"- **Conflicts with:** {', '.join(str(c) for c in conflicts)}")
    lines.append("")
    return lines


def compile_threads(
    internal_names: list[str],
    filters: dict,
    merge: bool,
    doc_prefix: str,
) -> list[dict]:
    """Compile active threads into markdown doc(s)."""
    status_filter = filters.get("threads_status")
    all_threads = []

    for name in internal_names:
        threads = get_active_threads(name)
        for t in threads:
            if not _passes_filters(t, filters):
                continue
            if not _status_matches(t.get("status", "open"), status_filter):
                continue
            all_threads.append({**t, "_source_project": name})

    if not all_threads:
        return []

    if merge:
        return [_build_merged_threads_doc(all_threads, doc_prefix)]

    return _build_per_project_threads_docs(all_threads, internal_names, doc_prefix)


def _build_merged_threads_doc(threads: list[dict], doc_prefix: str) -> dict:
    lines = [f"# Active Threads — All Projects\n"]
    lines.append(f"_Auto-synced from Forge OS. {len(threads)} threads. {_timestamp()}_\n")

    by_project: dict[str, list[dict]] = {}
    for t in threads:
        proj = t.get("_source_project", "Unknown")
        by_project.setdefault(proj, []).append(t)

    for proj in sorted(by_project):
        proj_threads = sorted(by_project[proj], key=lambda x: x.get("local_id", ""))
        lines.append(f"\n## {proj}\n")
        for t in proj_threads:
            lines.extend(_format_thread(t))

    return {
        "file_name": f"{doc_prefix}_threads_all.md",
        "content": "\n".join(lines),
        "item_count": len(threads),
    }


def _build_per_project_threads_docs(
    threads: list[dict],
    internal_names: list[str],
    doc_prefix: str,
) -> list[dict]:
    by_project: dict[str, list[dict]] = {}
    for t in threads:
        proj = t.get("_source_project", "Unknown")
        by_project.setdefault(proj, []).append(t)

    docs = []
    for name in internal_names:
        proj_threads = by_project.get(name, [])
        if not proj_threads:
            continue
        proj_threads.sort(key=lambda x: x.get("local_id", ""))
        lines = [f"# Active Threads — {name}\n"]
        lines.append(
            f"_Auto-synced from Forge OS. {len(proj_threads)} threads. {_timestamp()}_\n"
        )
        for t in proj_threads:
            lines.extend(_format_thread(t))

        safe_name = name.replace(" ", "_").replace("/", "_")
        docs.append({
            "file_name": f"{doc_prefix}_threads_{safe_name}.md",
            "content": "\n".join(lines),
            "item_count": len(proj_threads),
        })

    return docs


def _format_thread(t: dict) -> list[str]:
    local_id = t.get("local_id", "?")
    title = t.get("title", "")
    status = t.get("status", "open")
    priority = t.get("priority", "medium")
    blocked_by = t.get("blocked_by", [])
    hops = t.get("hops_since_validated", 0)

    lines = [f"### {local_id}: {title}\n"]
    lines.append(f"- **Status:** {status}")
    lines.append(f"- **Priority:** {priority}")
    lines.append(f"- **Hops since validated:** {hops}")
    if blocked_by:
        lines.append(f"- **Blocked by:** {', '.join(str(b) for b in blocked_by)}")
    lines.append("")
    return lines


def compile_flags(
    internal_names: list[str],
    filters: dict,
    merge: bool,
    doc_prefix: str,
) -> list[dict]:
    """Compile pending expedition flags into markdown doc(s)."""
    status_filter = filters.get("flags_status", "pending")
    all_flags = []

    for name in internal_names:
        flags = get_pending_flags(name) if status_filter == "pending" else []
        for f in flags:
            if not _passes_filters(f, filters):
                continue
            all_flags.append({**f, "_source_project": name})

    if not all_flags:
        return []

    # Group by category
    by_category: dict[str, list[dict]] = {}
    for f in all_flags:
        cat = f.get("category", "general")
        by_category.setdefault(cat, []).append(f)

    lines = [f"# Expedition Flags — {'All Projects' if merge else 'Pending'}\n"]
    lines.append(f"_Auto-synced from Forge OS. {len(all_flags)} flags. {_timestamp()}_\n")

    for cat in sorted(by_category):
        lines.append(f"\n## {cat.title()}\n")
        for f in by_category[cat]:
            desc = f.get("description", "")
            proj = f.get("_source_project", "")
            lines.append(f"- **[{proj}]** {desc}")
        lines.append("")

    file_name = f"{doc_prefix}_flags_all.md" if merge else f"{doc_prefix}_flags.md"
    return [{
        "file_name": file_name,
        "content": "\n".join(lines),
        "item_count": len(all_flags),
    }]


def compile_conflicts(
    internal_names: list[str],
    doc_prefix: str,
) -> list[dict]:
    """Compile conflicting decisions into a side-by-side markdown doc."""
    db = get_database()
    collection = db["decision_registry"]

    conflicts_found = []
    seen_pairs = set()

    for name in internal_names:
        decisions = list(collection.find(
            {"project": name, "status": "active", "conflicts_with": {"$ne": []}},
            {"_id": 0, "embedding": 0},
        ))

        for d in decisions:
            for conflict_uuid in d.get("conflicts_with", []):
                pair = tuple(sorted([d["uuid"], conflict_uuid]))
                if pair in seen_pairs:
                    continue
                seen_pairs.add(pair)

                other = collection.find_one(
                    {"uuid": conflict_uuid},
                    {"_id": 0, "embedding": 0},
                )
                if other is None:
                    continue

                conflicts_found.append({"a": d, "b": other})

    if not conflicts_found:
        return []

    lines = [f"# Decision Conflicts\n"]
    lines.append(
        f"_Auto-synced from Forge OS. {len(conflicts_found)} conflict pairs. {_timestamp()}_\n"
    )

    for i, pair in enumerate(conflicts_found, 1):
        a, b = pair["a"], pair["b"]
        lines.append(f"## Conflict {i}\n")
        lines.append(f"**{a.get('local_id', '?')}** ({a.get('project', '')}): {a.get('text', '')[:200]}")
        lines.append(f"- Tier: {a.get('epistemic_tier', '?')}\n")
        lines.append(f"**{b.get('local_id', '?')}** ({b.get('project', '')}): {b.get('text', '')[:200]}")
        lines.append(f"- Tier: {b.get('epistemic_tier', '?')}\n")

    return [{
        "file_name": f"{doc_prefix}_conflicts.md",
        "content": "\n".join(lines),
        "item_count": len(conflicts_found),
    }]


def _resolve_conversation_name(conv_id: str) -> str:
    """Resolve a conversation UUID to a human-readable name."""
    from vectordb.conversation_registry import get_conversation
    conv = get_conversation(conv_id)
    if conv:
        return conv.get("conversation_name", conv_id[:8])
    return conv_id[:12] + "..."


def _resolve_decision_names(decision_uuids: list[str]) -> list[str]:
    """Resolve decision UUIDs to local_id + short text."""
    db = get_database()
    names = []
    for uuid in decision_uuids:
        d = db["decision_registry"].find_one(
            {"uuid": uuid}, {"_id": 0, "local_id": 1, "text": 1, "project": 1}
        )
        if d:
            text = d.get("text", "")[:60]
            names.append(f"{d.get('local_id', '?')} ({d.get('project', '')}): {text}")
        else:
            names.append(uuid[:12] + "...")
    return names


def compile_lineage_summary(
    internal_names: list[str],
    doc_prefix: str,
) -> list[dict]:
    """Compile a lineage summary: chain counts, cross-project edges, carried/dropped.

    Searches edges by both internal names and Claude.ai-facing names,
    since edges may use either naming convention.
    """
    # Edges may use Claude.ai names (e.g. "The Nexus") or internal names
    # (e.g. "Reality Compiler"). Search with both sets to catch all.
    all_edges = []
    searched = set()
    for name in internal_names:
        if name not in searched:
            searched.add(name)
            all_edges.extend(get_full_graph(project=name))

    # Also search with no filter if we have wildcard-level coverage
    if len(internal_names) > 5:
        all_edges.extend(get_full_graph())

    # Deduplicate by edge_uuid
    seen = set()
    unique_edges = []
    for e in all_edges:
        eid = e.get("edge_uuid", id(e))
        if eid not in seen:
            seen.add(eid)
            unique_edges.append(e)

    if not unique_edges:
        return []

    cross_project = [
        e for e in unique_edges
        if e.get("source_project", "") != e.get("target_project", "")
        and e.get("source_project") and e.get("target_project")
    ]

    total_carried = sum(len(e.get("decisions_carried", [])) for e in unique_edges)
    total_dropped = sum(len(e.get("decisions_dropped", [])) for e in unique_edges)
    total_threads_carried = sum(len(e.get("threads_carried", [])) for e in unique_edges)
    total_threads_resolved = sum(len(e.get("threads_resolved", [])) for e in unique_edges)

    lines = [f"# Lineage Summary\n"]
    lines.append(f"_Auto-synced from Forge OS. {_timestamp()}_\n")
    lines.append(f"- **Total compression hops:** {len(unique_edges)}")
    lines.append(f"- **Cross-project hops:** {len(cross_project)}")
    lines.append(f"- **Decisions carried forward:** {total_carried}")
    lines.append(f"- **Decisions dropped:** {total_dropped}")
    lines.append(f"- **Threads carried forward:** {total_threads_carried}")
    lines.append(f"- **Threads resolved at hop:** {total_threads_resolved}")
    lines.append("")

    for i, e in enumerate(unique_edges, 1):
        src_name = _resolve_conversation_name(e.get("source_conversation", ""))
        tgt_name = _resolve_conversation_name(e.get("target_conversation", ""))
        src_proj = e.get("source_project", "")
        tgt_proj = e.get("target_project", "")
        tag = e.get("compression_tag", "")
        carried = e.get("decisions_carried", [])
        dropped = e.get("decisions_dropped", [])

        lines.append(f"## Hop {i}: {src_proj} → {tgt_proj}\n")
        lines.append(f"- **From:** {src_name}")
        lines.append(f"- **To:** {tgt_name}")
        if tag:
            lines.append(f"- **Compression tag:** {tag}")
        lines.append(f"- **Decisions carried:** {len(carried)}")
        lines.append(f"- **Decisions dropped:** {len(dropped)}")

        if carried:
            resolved = _resolve_decision_names(carried)
            lines.append("\n**Carried forward:**")
            for name in resolved:
                lines.append(f"- {name}")

        if dropped:
            resolved = _resolve_decision_names(dropped)
            lines.append("\n**Dropped:**")
            for name in resolved:
                lines.append(f"- {name}")

        lines.append("")

    return [{
        "file_name": f"{doc_prefix}_lineage_summary.md",
        "content": "\n".join(lines),
        "item_count": len(unique_edges),
    }]


# ---------------------------------------------------------------------------
# Compiler dispatch
# ---------------------------------------------------------------------------

_COMPILERS = {
    "decisions": compile_decisions,
    "threads": compile_threads,
    "flags": compile_flags,
    "conflicts": lambda names, filters, merge, prefix: compile_conflicts(names, prefix),
    "lineage_summary": lambda names, filters, merge, prefix: compile_lineage_summary(names, prefix),
}


def _compile_for_target(target: dict) -> list[dict]:
    """Run all compilers for a resolved target, return list of docs."""
    docs = []
    for dtype in target["data_types"]:
        compiler = _COMPILERS.get(dtype)
        if compiler is None:
            continue
        result = compiler(
            target["internal_names"],
            target["filters"],
            target["merge"],
            target["doc_prefix"],
        )
        docs.extend(result)
    return docs


# ---------------------------------------------------------------------------
# Cleanup: remove stale forge docs
# ---------------------------------------------------------------------------

def cleanup_old_docs(
    session: ClaudeSession,
    project_uuid: str,
    doc_prefix: str,
    new_file_names: set[str],
) -> int:
    """Delete previously-synced docs that aren't in the new compile output.

    Matches docs whose file_name starts with doc_prefix + "_" and ends
    with ".md", but aren't in new_file_names.

    Returns:
        Number of docs deleted.
    """
    existing_docs = session.get_project_docs(project_uuid)
    deleted = 0

    for doc in existing_docs:
        fname = doc.get("file_name", "")
        if not fname.startswith(f"{doc_prefix}_") or not fname.endswith(".md"):
            continue
        if fname not in new_file_names:
            try:
                session.delete_doc(project_uuid, doc["uuid"])
                deleted += 1
            except Exception:
                pass

    return deleted


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def sync_target(
    target: dict,
    session: Optional[ClaudeSession] = None,
    dry_run: bool = False,
) -> dict:
    """Compile and push all data types for one resolved target.

    Args:
        target: Resolved target dict from sync_manifest.resolve_target().
        session: Optional ClaudeSession (created if not provided and not dry_run).
        dry_run: If True, compile only — don't push to Claude.ai.

    Returns:
        Dict with project info, docs compiled, bytes pushed, docs cleaned up.
    """
    docs = _compile_for_target(target)

    result = {
        "project_uuid": target["project_uuid"],
        "claude_name": target["claude_name"],
        "docs_compiled": len(docs),
        "docs": [
            {
                "file_name": d["file_name"],
                "item_count": d["item_count"],
                "content_length": len(d["content"]),
            }
            for d in docs
        ],
        "docs_cleaned": 0,
        "dry_run": dry_run,
    }

    if dry_run:
        return result

    if session is None:
        session = get_session()

    new_file_names = {d["file_name"] for d in docs}

    # Clean up stale docs first
    cleaned = cleanup_old_docs(
        session, target["project_uuid"], target["doc_prefix"], new_file_names
    )
    result["docs_cleaned"] = cleaned

    # Upsert new docs
    for doc in docs:
        session.upsert_doc(
            target["project_uuid"], doc["file_name"], doc["content"]
        )

    return result


def sync_all(
    dry_run: bool = False,
    manifest_path: Optional[str] = None,
) -> dict:
    """Sync all enabled targets from the manifest.

    Creates one ClaudeSession and iterates all enabled targets with
    a 1-second delay between projects to be polite to the API.

    Args:
        dry_run: If True, compile only — don't push.
        manifest_path: Optional alternate manifest path.

    Returns:
        Dict with overall stats and per-target results.
    """
    manifest = load_manifest(manifest_path)
    targets = resolve_all_targets(manifest)

    session = None
    if not dry_run:
        session = get_session()

    results = []
    for i, target in enumerate(targets):
        target_result = sync_target(target, session=session, dry_run=dry_run)
        results.append(target_result)

        # Rate limit: 1s between projects (skip after last)
        if not dry_run and i < len(targets) - 1:
            time.sleep(1)

    total_docs = sum(r["docs_compiled"] for r in results)
    total_cleaned = sum(r["docs_cleaned"] for r in results)

    return {
        "targets_synced": len(results),
        "total_docs_compiled": total_docs,
        "total_docs_cleaned": total_cleaned,
        "dry_run": dry_run,
        "results": results,
    }


def sync_one(
    project_uuid: str,
    dry_run: bool = False,
    manifest_path: Optional[str] = None,
) -> dict:
    """Sync a single target by project UUID.

    Args:
        project_uuid: Claude.ai project UUID.
        dry_run: If True, compile only.
        manifest_path: Optional alternate manifest path.

    Returns:
        Sync result dict for the target.

    Raises:
        ValueError: If the project UUID isn't in the manifest.
    """
    manifest = load_manifest(manifest_path)
    target = resolve_target(manifest, project_uuid)

    if target is None:
        raise ValueError(f"Project UUID {project_uuid} not found in manifest")

    if not target["enabled"]:
        return {
            "project_uuid": project_uuid,
            "claude_name": target["claude_name"],
            "status": "skipped",
            "reason": "disabled in manifest",
        }

    return sync_target(target, dry_run=dry_run)
