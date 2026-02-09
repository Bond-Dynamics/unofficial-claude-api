#!/usr/bin/env python3
"""Forge OS Sync Pipeline — Parse compression archives and sync to registries.

Parses markdown archives produced by `compress --lossless` and syncs
decisions, threads, and lineage into MongoDB via the vectordb registries.

Usage:
    python scripts/sync_compression.py \
        --project "Forge OS" \
        --project-uuid "abc-123-..." \
        --file data/artifacts/.../conversation_archive.md

    # Or from clipboard:
    python scripts/sync_compression.py \
        --project "Forge OS" \
        --project-uuid "abc-123-..." \
        --clipboard
"""

import argparse
import hashlib
import re
import subprocess
import sys
import uuid as uuid_mod
from datetime import datetime, timezone

# Add parent dir to path for imports
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from vectordb.compression_registry import compute_checksum, register_compression
from vectordb.db import get_database
from vectordb.decision_registry import (
    increment_decision_hops,
    upsert_decision,
)
from vectordb.events import emit_event
from vectordb.lineage import add_edge
from vectordb.thread_registry import (
    increment_thread_hops,
    upsert_thread,
)
from vectordb.uuidv8 import conversation_id as derive_conversation_id


# ---------------------------------------------------------------------------
# Archive parser
# ---------------------------------------------------------------------------

# Decision section: ### D001: Title
_DECISION_HEADER = re.compile(
    r"^###\s+(D\d{3,4}):\s+(.+)$", re.MULTILINE
)

# Thread section: ### T001: Title  OR  - T001: Title
_THREAD_HEADER = re.compile(
    r"^(?:###|-)\s+(T\d{3,4}):\s+(.+)$", re.MULTILINE
)

# Artifact section: ### Artifact A001: Title
_ARTIFACT_HEADER = re.compile(
    r"^###\s+Artifact\s+(A\d{3,4}):\s+(.+)$", re.MULTILINE
)

# Field patterns inside decision/thread blocks
_FIELD_TIER = re.compile(r"\*\*Tier:\*\*\s*([\d.]+)")
_FIELD_TURN = re.compile(r"\*\*Turn:\*\*\s*(\d+)")
_FIELD_DECISION = re.compile(r"\*\*Decision:\*\*\s*(.+?)(?=\n\s*-\s*\*\*|\n###|\Z)", re.DOTALL)
_FIELD_RATIONALE = re.compile(r"\*\*Rationale:\*\*\s*(.+?)(?=\n\s*-\s*\*\*|\n###|\Z)", re.DOTALL)
_FIELD_DEPENDENCIES = re.compile(r"\*\*Dependencies:\*\*\s*(.+?)(?=\n\s*-\s*\*\*|\n###|\Z)", re.DOTALL)
_FIELD_STATUS = re.compile(r"\*\*(?:Final\s+)?Status:\*\*\s*(.+)")
_FIELD_CONTEXT = re.compile(r"\*\*Context:\*\*\s*(.+?)(?=\n\s*-\s*\*\*|\n###|\Z)", re.DOTALL)
_FIELD_PRIORITY = re.compile(r"\*\*Priority:\*\*\s*(\w+)")
_FIELD_BLOCKED_BY = re.compile(r"\*\*Blocked\s*By:\*\*\s*(.+)")
_FIELD_RESOLUTION = re.compile(r"\*\*Resolution:\*\*\s*(.+)")

# Metadata section
_METADATA_TAG = re.compile(
    r"\*\*(?:Last\s+)?Compress(?:ed|ion)\s+Tag:\*\*\s*(.+)", re.IGNORECASE
)
_METADATA_TURNS = re.compile(
    r"\*\*Turns:\*\*\s*(\d+)", re.IGNORECASE
)
_METADATA_PREVIOUS = re.compile(
    r"\*\*Previous\s+Session:\*\*\s*(.+)", re.IGNORECASE
)

# YAML decision block (alternative format)
_YAML_DECISION_ID = re.compile(r"^\s*-\s*id:\s*(D\d{3,4})", re.MULTILINE)
_YAML_DECISION_TEXT = re.compile(r"^\s*decision:\s*\"?(.+?)\"?\s*$", re.MULTILINE)
_YAML_DECISION_RATIONALE = re.compile(r"^\s*rationale:\s*\"?(.+?)\"?\s*$", re.MULTILINE)
_YAML_DECISION_CONFIDENCE = re.compile(r"^\s*confidence:\s*(\w+)", re.MULTILINE)
_YAML_DECISION_TURN = re.compile(r"^\s*turn:\s*(\d+)", re.MULTILINE)
_YAML_DECISION_DEPS = re.compile(r"^\s*dependencies:\s*\[(.+?)\]", re.MULTILINE)


def parse_archive(text):
    """Parse a markdown compression archive into structured data.

    Supports two formats:
      1. Rich markdown: ### D001: Title with **Tier:**, **Decision:**, etc.
      2. YAML decision log: ```yaml decisions: - id: D001 ...```

    Args:
        text: Raw markdown archive text.

    Returns:
        Dict with keys: decisions, threads, metadata.
    """
    metadata = _parse_metadata(text)
    decisions = _parse_decisions_markdown(text)

    # If markdown parsing found nothing, try YAML format
    if not decisions:
        decisions = _parse_decisions_yaml(text)

    threads = _parse_threads(text)
    artifacts = _parse_artifact_ids(text)

    return {
        "decisions": decisions,
        "threads": threads,
        "artifacts": artifacts,
        "metadata": metadata,
    }


def _parse_metadata(text):
    """Extract archive metadata from the ## Metadata section."""
    meta = {
        "compression_tag": "",
        "turns": 0,
        "previous_session": "",
        "status": "",
    }

    match = _METADATA_TAG.search(text)
    if match:
        meta["compression_tag"] = match.group(1).strip()

    match = _METADATA_TURNS.search(text)
    if match:
        meta["turns"] = int(match.group(1))

    match = _METADATA_PREVIOUS.search(text)
    if match:
        meta["previous_session"] = match.group(1).strip()

    match = _FIELD_STATUS.search(text[:500])
    if match:
        meta["status"] = match.group(1).strip()

    return meta


def _parse_decisions_markdown(text):
    """Parse ### D001: Title format decisions."""
    decisions = []
    headers = list(_DECISION_HEADER.finditer(text))

    for i, header in enumerate(headers):
        local_id = header.group(1)
        title = header.group(2).strip()

        # Extract section text between this header and the next
        start = header.end()
        end = headers[i + 1].start() if i + 1 < len(headers) else len(text)
        section = text[start:end]

        decision = {
            "local_id": local_id,
            "title": title,
            "text": "",
            "tier": None,
            "turn": None,
            "rationale": "",
            "dependencies": [],
        }

        # Try **Decision:** field first
        match = _FIELD_DECISION.search(section)
        if match:
            decision["text"] = match.group(1).strip()
        else:
            # Fall back to title as text
            decision["text"] = title

        match = _FIELD_TIER.search(section)
        if match:
            try:
                decision["tier"] = float(match.group(1))
            except ValueError:
                pass

        match = _FIELD_TURN.search(section)
        if match:
            decision["turn"] = int(match.group(1))

        match = _FIELD_RATIONALE.search(section)
        if match:
            decision["rationale"] = match.group(1).strip()

        match = _FIELD_DEPENDENCIES.search(section)
        if match:
            deps_text = match.group(1).strip()
            decision["dependencies"] = [
                d.strip() for d in re.split(r"[,;]", deps_text) if d.strip()
            ]

        decisions.append(decision)

    return decisions


def _parse_decisions_yaml(text):
    """Parse YAML-format decision log blocks."""
    decisions = []

    # Find YAML code blocks containing "decisions:"
    yaml_blocks = re.findall(
        r"```ya?ml\s*\n(.*?)```", text, re.DOTALL
    )

    for block in yaml_blocks:
        if "decisions:" not in block:
            continue

        # Split by "- id:" entries
        entries = re.split(r"(?=^\s*-\s*id:)", block, flags=re.MULTILINE)

        for entry in entries:
            id_match = _YAML_DECISION_ID.search(entry)
            if not id_match:
                continue

            local_id = id_match.group(1)
            decision = {
                "local_id": local_id,
                "title": "",
                "text": "",
                "tier": None,
                "turn": None,
                "rationale": "",
                "dependencies": [],
            }

            match = _YAML_DECISION_TEXT.search(entry)
            if match:
                decision["text"] = match.group(1).strip()
                decision["title"] = decision["text"][:100]

            match = _YAML_DECISION_RATIONALE.search(entry)
            if match:
                decision["rationale"] = match.group(1).strip()

            match = _YAML_DECISION_CONFIDENCE.search(entry)
            if match:
                confidence_map = {
                    "highest": 0.9, "high": 0.7, "medium": 0.5,
                    "low": 0.3, "speculative": 0.2,
                }
                decision["tier"] = confidence_map.get(
                    match.group(1).lower(), 0.5
                )

            match = _YAML_DECISION_TURN.search(entry)
            if match:
                decision["turn"] = int(match.group(1))

            match = _YAML_DECISION_DEPS.search(entry)
            if match:
                deps = [d.strip().strip("'\"") for d in match.group(1).split(",")]
                decision["dependencies"] = [d for d in deps if d]

            decisions.append(decision)

    return decisions


def _parse_threads(text):
    """Parse thread entries from archive."""
    threads = []
    headers = list(_THREAD_HEADER.finditer(text))

    for i, header in enumerate(headers):
        local_id = header.group(1)
        title = header.group(2).strip()

        start = header.end()
        end = headers[i + 1].start() if i + 1 < len(headers) else len(text)
        section = text[start:end]

        thread = {
            "local_id": local_id,
            "title": title,
            "status": "open",
            "priority": "medium",
            "blocked_by": [],
            "resolution": "",
            "tier": None,
        }

        match = _FIELD_STATUS.search(section)
        if match:
            status_text = match.group(1).lower().strip()
            if "resolved" in status_text:
                thread["status"] = "resolved"
            elif "blocked" in status_text:
                thread["status"] = "blocked"

        match = _FIELD_PRIORITY.search(section)
        if match:
            thread["priority"] = match.group(1).lower()

        match = _FIELD_BLOCKED_BY.search(section)
        if match:
            thread["blocked_by"] = [
                b.strip() for b in match.group(1).split(",") if b.strip()
            ]

        match = _FIELD_RESOLUTION.search(section)
        if match:
            thread["resolution"] = match.group(1).strip()

        match = _FIELD_TIER.search(section)
        if match:
            try:
                thread["tier"] = float(match.group(1))
            except ValueError:
                pass

        threads.append(thread)

    return threads


def _parse_artifact_ids(text):
    """Extract artifact local_ids (A001, A002, ...) from archive."""
    return [m.group(1) for m in _ARTIFACT_HEADER.finditer(text)]


# ---------------------------------------------------------------------------
# Sync engine
# ---------------------------------------------------------------------------

def sync_archive(
    parsed,
    project,
    project_uuid,
    conversation_id=None,
    source_conversation_id=None,
    archive_text=None,
    dry_run=False,
    db=None,
):
    """Sync a parsed archive into the registries.

    Args:
        parsed: Output of parse_archive().
        project: Project display name.
        project_uuid: Project UUIDv8 (uuid.UUID).
        conversation_id: UUID of this conversation (optional, derived if absent).
        source_conversation_id: UUID of the source conversation for lineage.
        archive_text: Raw archive text (for checksum computation).
        dry_run: If True, log actions without writing to DB.
        db: Optional database instance.

    Returns:
        Summary dict with counts of synced items and any conflicts.
    """
    if db is None:
        db = get_database()

    if conversation_id is None:
        tag = parsed["metadata"].get("compression_tag", "unknown")
        conversation_id = derive_conversation_id(
            project_uuid, tag, int(datetime.now(timezone.utc).timestamp() * 1000)
        )
    elif isinstance(conversation_id, str):
        conversation_id = uuid_mod.UUID(conversation_id)

    summary = {
        "decisions_synced": 0,
        "decisions_validated": 0,
        "decisions_inserted": 0,
        "decisions_updated": 0,
        "threads_synced": 0,
        "threads_inserted": 0,
        "threads_updated": 0,
        "lineage_created": False,
        "compression_registered": False,
        "conflicts": [],
        "dry_run": dry_run,
    }

    decision_uuids = set()
    thread_uuids = set()

    # Sync decisions
    for dec in parsed["decisions"]:
        if dry_run:
            summary["decisions_synced"] += 1
            continue

        result = upsert_decision(
            local_id=dec["local_id"],
            text=dec["text"],
            project=project,
            project_uuid=project_uuid,
            originated_conversation_id=conversation_id,
            epistemic_tier=dec.get("tier"),
            status="active",
            dependencies=dec.get("dependencies"),
            rationale=dec.get("rationale"),
            db=db,
        )

        decision_uuids.add(result["uuid"])
        summary["decisions_synced"] += 1
        action = result["action"]
        if action == "inserted":
            summary["decisions_inserted"] += 1
        elif action == "validated":
            summary["decisions_validated"] += 1
        elif action == "updated":
            summary["decisions_updated"] += 1

        if result.get("conflicts"):
            summary["conflicts"].extend(result["conflicts"])

    # Sync threads
    for thr in parsed["threads"]:
        if dry_run:
            summary["threads_synced"] += 1
            continue

        result = upsert_thread(
            local_id=thr["local_id"],
            title=thr["title"],
            project=project,
            project_uuid=project_uuid,
            first_seen_conversation_id=conversation_id,
            status=thr.get("status", "open"),
            priority=thr.get("priority", "medium"),
            blocked_by=thr.get("blocked_by"),
            resolution=thr.get("resolution"),
            epistemic_tier=thr.get("tier"),
            db=db,
        )

        thread_uuids.add(result["uuid"])
        summary["threads_synced"] += 1
        if result["action"] == "inserted":
            summary["threads_inserted"] += 1
        else:
            summary["threads_updated"] += 1

    # Increment hops for items NOT in this archive
    if not dry_run:
        increment_decision_hops(project, exclude_uuids=decision_uuids, db=db)
        increment_thread_hops(project, exclude_uuids=thread_uuids, db=db)

    # Create lineage edge
    if source_conversation_id and not dry_run:
        if isinstance(source_conversation_id, str):
            source_conversation_id = uuid_mod.UUID(source_conversation_id)

        edge_result = add_edge(
            source_conversation=str(source_conversation_id),
            target_conversation=str(conversation_id),
            compression_tag=parsed["metadata"].get("compression_tag", ""),
            decisions_carried=list(decision_uuids),
            threads_carried=list(thread_uuids),
            db=db,
        )
        summary["lineage_created"] = True

    # Register compression tag
    compression_tag = parsed["metadata"].get("compression_tag", "")
    if compression_tag and not dry_run:
        checksum = compute_checksum(archive_text) if archive_text else None
        target_convs = [str(conversation_id)] if conversation_id else []
        register_compression(
            compression_tag=compression_tag,
            project=project,
            source_conversation=str(source_conversation_id) if source_conversation_id else "",
            decisions_captured=[d["local_id"] for d in parsed["decisions"]],
            threads_captured=[t["local_id"] for t in parsed["threads"]],
            artifacts_captured=parsed.get("artifacts", []),
            archive_checksum=checksum,
            target_conversations=target_convs,
            db=db,
        )
        summary["compression_registered"] = True

    if not dry_run:
        emit_event(
            "graph.sync.completed",
            {
                "project": project,
                "conversation_id": str(conversation_id),
                "decisions_synced": summary["decisions_synced"],
                "threads_synced": summary["threads_synced"],
                "conflict_count": len(summary["conflicts"]),
            },
            db=db,
        )

    return summary


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _read_from_clipboard():
    """Read text from macOS clipboard."""
    try:
        result = subprocess.run(
            ["pbpaste"], capture_output=True, text=True, check=True,
        )
        return result.stdout
    except (subprocess.CalledProcessError, FileNotFoundError) as err:
        raise RuntimeError(f"Failed to read clipboard: {err}") from err


def main():
    parser = argparse.ArgumentParser(
        description="Sync a compression archive to Forge OS registries"
    )
    parser.add_argument("--project", required=True, help="Project display name")
    parser.add_argument("--project-uuid", required=True, help="Project UUIDv8")
    parser.add_argument("--file", help="Path to archive markdown file")
    parser.add_argument("--clipboard", action="store_true", help="Read from clipboard")
    parser.add_argument("--stdin", action="store_true", help="Read from stdin")
    parser.add_argument("--conversation-id", help="Conversation UUID for this archive")
    parser.add_argument("--source-conversation-id", help="Source conversation UUID for lineage")
    parser.add_argument("--dry-run", action="store_true", help="Parse only, don't write to DB")

    args = parser.parse_args()

    # Read archive text
    if args.file:
        archive_text = Path(args.file).read_text(encoding="utf-8")
    elif args.clipboard:
        archive_text = _read_from_clipboard()
    elif args.stdin:
        archive_text = sys.stdin.read()
    else:
        parser.error("One of --file, --clipboard, or --stdin is required")

    project_uuid = uuid_mod.UUID(args.project_uuid)

    # Parse
    parsed = parse_archive(archive_text)
    print(f"Parsed: {len(parsed['decisions'])} decisions, {len(parsed['threads'])} threads")
    print(f"Metadata: {parsed['metadata']}")

    if args.dry_run:
        print("\n[DRY RUN] Would sync:")
        for dec in parsed["decisions"]:
            print(f"  Decision {dec['local_id']}: {dec['text'][:80]}...")
        for thr in parsed["threads"]:
            print(f"  Thread {thr['local_id']}: {thr['title']}")
        return

    # Sync
    summary = sync_archive(
        parsed=parsed,
        project=args.project,
        project_uuid=project_uuid,
        conversation_id=args.conversation_id,
        source_conversation_id=args.source_conversation_id,
        archive_text=archive_text,
        dry_run=False,
    )

    print(f"\nSync complete:")
    print(f"  Decisions: {summary['decisions_synced']} synced "
          f"({summary['decisions_inserted']} new, "
          f"{summary['decisions_validated']} validated, "
          f"{summary['decisions_updated']} updated)")
    print(f"  Threads: {summary['threads_synced']} synced "
          f"({summary['threads_inserted']} new, "
          f"{summary['threads_updated']} updated)")
    print(f"  Lineage: {'created' if summary['lineage_created'] else 'skipped'}")
    print(f"  Compression: {'registered' if summary['compression_registered'] else 'skipped'}")
    if summary["conflicts"]:
        print(f"  Conflicts detected: {len(summary['conflicts'])}")
        for c in summary["conflicts"]:
            print(f"    - {c['signal']}: {c['existing_uuid'][:8]}... "
                  f"(severity: {c['severity']})")


if __name__ == "__main__":
    main()
