#!/usr/bin/env python3
"""Forge OS — Extract threads from raw conversation JSON files.

Scans data/conversations/*.json for thread declarations in multiple
formats used across compression archives and registers them into the
thread_registry via upsert_thread().

Supported formats:
    1. **T### (PRIORITY):** description
    2. **OT###:** description
    3. | T### | description | priority | (table rows)
    4. - T###: description (bullet lists)
    5. Numbered items under "Open Threads" headers

Usage:
    python scripts/extract_threads.py
    python scripts/extract_threads.py --dry-run
    python scripts/extract_threads.py --project "The Cartographer's Codex"
"""

import argparse
import json
import os
import re
import sys
import uuid as uuid_mod
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from vectordb.conversation_registry import get_conversation
from vectordb.db import get_database
from vectordb.thread_registry import upsert_thread
from vectordb.uuidv8 import v5

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "conversations"

# ---------------------------------------------------------------------------
# Regex patterns for thread extraction
# ---------------------------------------------------------------------------

# **T001 (HIGH):** description
PAT_T_BOLD = re.compile(
    r"\*\*T(\d{3})\s*\((\w+)\):\*\*\s*(.+?)(?=\n\*\*T\d{3}|\n\n|\Z)",
    re.DOTALL,
)

# **OT001:** description  (may be preceded by - or * bullet)
PAT_OT_BOLD = re.compile(
    r"\*\*OT(\d{3}):\*\*\s*(.+?)(?=\n[-\*\s]*\*\*OT\d{3}|\n\n|\Z)",
    re.DOTALL,
)

# | T001 | description | priority | notes |
PAT_TABLE = re.compile(
    r"\|\s*T(\d{3})\s*\|\s*(.+?)\s*\|\s*(\w+)\s*\|"
)

# - T001: description  or  - **T001:** description
PAT_BULLET = re.compile(
    r"[-\*]\s+\*?\*?T(\d{3})\*?\*?:\s*(.+)"
)

# "Open Threads" section header
PAT_OPEN_HEADER = re.compile(r"(?i)open\s+threads?:?\s*\n")

# Compression instruction (false positive filter for numbered lists)
PAT_COMPRESSION_INSTR = re.compile(
    r"(?i)\*\*(high|medium|low)\s*\(.*?(compress|summarize|discard)",
)


def _clean_title(raw: str) -> str:
    """Strip markdown formatting and truncate."""
    title = raw.strip().replace("\n", " ")
    title = re.sub(r"\s+", " ", title)
    return title[:300]


def _normalize_priority(raw: str) -> str:
    """Normalize priority strings to high/medium/low."""
    raw = raw.lower().strip()
    if raw in ("high", "medium", "low"):
        return raw
    if raw in ("critical", "urgent"):
        return "high"
    return "medium"


def extract_from_text(text: str) -> list[dict]:
    """Extract all thread declarations from a block of text.

    Returns list of dicts with local_id, priority, title, format.
    """
    threads = []
    seen_ids = set()

    def _add(local_id, priority, title, fmt):
        if local_id in seen_ids:
            return
        title = _clean_title(title)
        if not title or len(title) < 5:
            return
        seen_ids.add(local_id)
        threads.append({
            "local_id": local_id,
            "priority": _normalize_priority(priority),
            "title": title,
            "format": fmt,
        })

    # Pattern 1: **T### (PRIORITY):** description
    for m in PAT_T_BOLD.finditer(text):
        _add(f"T{m.group(1)}", m.group(2), m.group(3), "T###_bold")

    # Pattern 2: **OT###:** description
    for m in PAT_OT_BOLD.finditer(text):
        _add(f"OT{m.group(1)}", "medium", m.group(2), "OT###_bold")

    # Pattern 3: Table rows | T### | desc | priority |
    for m in PAT_TABLE.finditer(text):
        _add(f"T{m.group(1)}", m.group(3), m.group(2), "table")

    # Pattern 4: Bullet points - T###: desc
    for m in PAT_BULLET.finditer(text):
        title = m.group(2)
        # Extract embedded priority from title like "Phase 0-A content (High)"
        priority = "medium"
        prio_match = re.search(r"\((\w+)\)\s*$", title)
        if prio_match and prio_match.group(1).lower() in ("high", "medium", "low"):
            priority = prio_match.group(1).lower()
            title = title[:prio_match.start()].strip()
        _add(f"T{m.group(1)}", priority, title, "bullet")

    # Pattern 5: Numbered items under "Open Threads" header
    for header_match in PAT_OPEN_HEADER.finditer(text):
        after = text[header_match.end():]
        block = re.split(r"\n\n|\n##|\n---", after)[0]
        for line in block.split("\n"):
            line = line.strip()
            # Skip lines that are compression instructions
            if PAT_COMPRESSION_INSTR.search(line):
                continue
            nm = re.match(r"(\d+)\.\s+(.+)", line)
            if nm:
                num = int(nm.group(1))
                title = nm.group(2).strip()
                # Strip leading bold markers
                title = re.sub(r"^\*\*.*?\*\*\s*", "", title)
                local_id = f"OT{num:03d}"
                _add(local_id, "medium", title, "numbered_list")

    return threads


def extract_all_conversations(
    project_filter=None,
    data_dir=None,
) -> list[dict]:
    """Scan all conversation JSON files for thread declarations.

    Args:
        project_filter: Only process conversations from this Claude.ai project.
        data_dir: Override data directory path.

    Returns:
        List of extracted thread dicts with conversation context.
    """
    data_path = Path(data_dir) if data_dir else DATA_DIR
    if not data_path.exists():
        print(f"Data directory not found: {data_path}")
        return []

    all_threads = []

    for fname in sorted(os.listdir(data_path)):
        if not fname.endswith(".json"):
            continue

        filepath = data_path / fname
        with open(filepath) as f:
            data = json.load(f)

        conv_id = data.get("uuid", fname.replace(".json", ""))
        conv_name = data.get("name", "unnamed")
        project = data.get("project", {})
        project_name = (
            project.get("name", "Unknown")
            if isinstance(project, dict)
            else "Unknown"
        )

        if project_filter and project_name != project_filter:
            continue

        conv_threads = []
        for msg in data.get("chat_messages", []):
            for content in msg.get("content", []):
                text = content.get("text", "")
                extracted = extract_from_text(text)
                for t in extracted:
                    t["conversation_id"] = conv_id
                    t["conversation_name"] = conv_name
                    t["project_name"] = project_name
                conv_threads.extend(extracted)

        # Deduplicate within this conversation (same local_id)
        seen = set()
        for t in conv_threads:
            key = (conv_id, t["local_id"])
            if key not in seen:
                seen.add(key)
                all_threads.append(t)

    return all_threads


def register_threads(
    threads: list[dict],
    dry_run: bool = False,
    db=None,
) -> dict:
    """Register extracted threads into the thread_registry.

    Args:
        threads: List of thread dicts from extract_all_conversations().
        dry_run: If True, count without writing.
        db: Optional database instance.

    Returns:
        Summary dict with counts.
    """
    if db is None:
        db = get_database()

    summary = {
        "total": len(threads),
        "inserted": 0,
        "updated": 0,
        "errors": 0,
        "by_project": {},
    }

    for t in threads:
        project_name = t["project_name"]
        summary["by_project"].setdefault(project_name, 0)

        if dry_run:
            summary["by_project"][project_name] += 1
            continue

        try:
            project_uuid = v5(f"project:{project_name}")

            # Convert conversation_id to uuid.UUID for thread_id derivation
            try:
                conv_uuid = uuid_mod.UUID(t["conversation_id"])
            except (ValueError, AttributeError):
                conv_uuid = v5(t["conversation_id"])

            result = upsert_thread(
                local_id=t["local_id"],
                title=t["title"],
                project=project_name,
                project_uuid=project_uuid,
                first_seen_conversation_id=conv_uuid,
                status="open",
                priority=t["priority"],
                db=db,
            )

            if result["action"] == "inserted":
                summary["inserted"] += 1
            else:
                summary["updated"] += 1

            summary["by_project"][project_name] += 1

        except Exception as err:
            summary["errors"] += 1
            print(f"  Error registering {t['local_id']} from {t['conversation_name']}: {err}")

    return summary


def main():
    parser = argparse.ArgumentParser(
        description="Extract threads from raw conversation JSON and register them",
    )
    parser.add_argument(
        "--project",
        help="Only extract from this Claude.ai project name",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Extract and count without writing to MongoDB",
    )
    parser.add_argument(
        "--data-dir",
        help="Override data/conversations directory",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Show each extracted thread",
    )

    args = parser.parse_args()

    print("Extracting threads from raw conversations...")
    if args.project:
        print(f"  Filtering: {args.project}")
    if args.dry_run:
        print("  [DRY RUN]")

    threads = extract_all_conversations(
        project_filter=args.project,
        data_dir=args.data_dir,
    )

    if args.verbose or args.dry_run:
        print(f"\nExtracted {len(threads)} threads:\n")
        by_conv = {}
        for t in threads:
            by_conv.setdefault(t["conversation_name"], []).append(t)
        for conv_name, conv_threads in sorted(by_conv.items()):
            proj = conv_threads[0]["project_name"]
            print(f"  {conv_name} ({proj}):")
            for t in sorted(conv_threads, key=lambda x: x["local_id"]):
                print(f"    {t['local_id']} ({t['priority']}) [{t['format']}]: {t['title'][:80]}")
            print()

    if not threads:
        print("No threads found.")
        return

    summary = register_threads(threads, dry_run=args.dry_run)

    label = "(dry run)" if args.dry_run else "complete"
    print(f"\nThread extraction {label}:")
    print(f"  Total extracted: {summary['total']}")
    if not args.dry_run:
        print(f"  Inserted: {summary['inserted']}")
        print(f"  Updated: {summary['updated']}")
    if summary["errors"]:
        print(f"  Errors: {summary['errors']}")

    print(f"\nBy project:")
    for project, count in sorted(
        summary["by_project"].items(), key=lambda x: -x[1]
    ):
        print(f"  {project}: {count}")

    print("\nDone.")


if __name__ == "__main__":
    main()
