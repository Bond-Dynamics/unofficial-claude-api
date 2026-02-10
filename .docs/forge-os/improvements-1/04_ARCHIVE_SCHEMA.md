# Improvement 4: Strict Archive Schema

## Priority: 4
## Effort: Medium
## Value: Medium

---

## Context & Motivation

The conversation archive (exchange_004, sharpening question #1) flagged archive format stability as a risk:

> "Is it stable enough to parse reliably? What's the failure mode if parsing fails? Should the compression skill be updated to output machine-parseable YAML alongside human-readable markdown?"

The recommendation was: **Define a canonical machine-readable section in the archive format that the sync script parses. Human-readable parts can vary; machine section must be strict.**

Currently, `sync_compression.py` parses archives using fragile regex patterns:
- `_DECISION_HEADER = re.compile(r"^###\s+(D\d{3,4}):\s+(.+)$", ...)` (line 52)
- `_FIELD_TIER = re.compile(r"\*\*Tier:\*\*\s*([\d.]+)")` (line 67)
- Various `_FIELD_*` patterns for each metadata field

If an archive uses slightly different formatting (e.g., `## D001` instead of `### D001`, or `**Confidence:**` instead of `**Tier:**`), parsing silently fails -- decisions are missed with no error. This is the "silent data loss" failure mode.

---

## Existing Code Surface

### Archive parser (sync_compression.py:98-341)

Two format paths:
1. **Rich markdown** (lines 157-213): Regex-based, fragile
2. **YAML fallback** (lines 216-278): Only triggered if markdown finds zero decisions

Neither format has a schema definition, version identifier, or validation step.

### Compression skill (external to this codebase)

The `compress --lossless` skill in Claude Projects produces the archives. It outputs markdown with decisions, threads, insights, and metadata sections. The format is defined by the skill's system prompt, not by a formal schema.

### Metadata parsing (sync_compression.py:129-154)

Extracts compression_tag, turns, previous_session, status via regex. No validation that required fields are present.

---

## Architecture

```
┌──────────────────────────────────────────────────────────┐
│  Archive markdown (human-readable)                       │
│                                                          │
│  ## Decisions                                            │
│  ### D001: Use PostgreSQL                                │
│  - **Tier:** 0.8                                         │
│  - **Decision:** Full text here...                       │
│                                                          │
│  <!-- FORGE_OS_MACHINE_BLOCK_START                       │
│  version: 2                                              │
│  decisions:                                              │
│    - id: D001                                            │
│      text: "Use PostgreSQL for storage"                  │
│      tier: 0.8                                           │
│      rationale: "Mature, reliable..."                    │
│      dependencies: []                                    │
│  threads:                                                │
│    - id: T001                                            │
│      title: "Token rotation strategy"                    │
│      status: open                                        │
│      priority: medium                                    │
│      blocked_by: [D031]                                  │
│  metadata:                                               │
│    compression_tag: "forge-os-2026-02-10"                │
│    project: "Forge OS"                                   │
│    source_conversation: "abc-123"                        │
│    turns: 42                                             │
│  FORGE_OS_MACHINE_BLOCK_END -->                          │
└──────────────────────────────────────────────────────────┘
```

The machine block is embedded as an HTML comment, invisible in rendered markdown but always present and parseable.

---

## Files to Create

### 1. `vectordb/archive_schema.py` (~150 lines)

Schema definition, validation, and extraction for the machine-readable block.

```python
# --- Constants ---
SCHEMA_VERSION = 2
MACHINE_BLOCK_START = "<!-- FORGE_OS_MACHINE_BLOCK_START"
MACHINE_BLOCK_END = "FORGE_OS_MACHINE_BLOCK_END -->"

# --- Schema definition ---
REQUIRED_DECISION_FIELDS = {"id", "text"}
OPTIONAL_DECISION_FIELDS = {"tier", "rationale", "dependencies", "turn", "status"}

REQUIRED_THREAD_FIELDS = {"id", "title"}
OPTIONAL_THREAD_FIELDS = {"status", "priority", "blocked_by", "resolution", "tier"}

REQUIRED_METADATA_FIELDS = {"compression_tag", "project"}
OPTIONAL_METADATA_FIELDS = {"source_conversation", "turns", "previous_session"}


# --- Public API ---

def extract_machine_block(archive_text):
    """Extract the YAML machine block from an archive.

    Returns:
        Parsed dict with 'decisions', 'threads', 'metadata', 'version'.
        Returns None if no machine block found.
    """

def validate_machine_block(parsed):
    """Validate a parsed machine block against the schema.

    Returns:
        List of validation errors (empty if valid).
        Each error: {"field": "decisions[0].text", "error": "missing required field"}
    """

def generate_machine_block(decisions, threads, metadata):
    """Generate a YAML machine block string from structured data.

    Used by the compression skill to append a machine block to archives.
    Returns: string ready to append to archive markdown.
    """

def upgrade_schema(parsed, from_version):
    """Upgrade a machine block from an older schema version.

    Handles forward-compatible transformations.
    """


class ArchiveParseError(Exception):
    """Raised when archive parsing fails validation."""

    def __init__(self, errors):
        self.errors = errors
        super().__init__(f"Archive validation failed: {len(errors)} errors")
```

---

## Files to Modify

### 2. `scripts/sync_compression.py` (~+30 lines)

Update `parse_archive()` to try machine block first, fall back to regex:

```python
def parse_archive(text):
    # Priority 1: Machine-readable block
    machine_block = extract_machine_block(text)
    if machine_block is not None:
        errors = validate_machine_block(machine_block)
        if errors:
            print(f"WARNING: Machine block has {len(errors)} validation errors:")
            for err in errors:
                print(f"  - {err['field']}: {err['error']}")
            # Fall through to regex parsing
        else:
            return machine_block

    # Priority 2: Regex parsing (legacy/fallback)
    metadata = _parse_metadata(text)
    decisions = _parse_decisions_markdown(text)
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
```

### 3. `scripts/prepare_compression.py` (~+15 lines)

At the end of `assemble_compression_context()`, include a note reminding the user (or Claude) to include the machine block in the output:

```python
sections.append("")
sections.append("### Machine Block Reminder")
sections.append("When compressing, include a FORGE_OS_MACHINE_BLOCK in the archive.")
sections.append("See: vectordb/archive_schema.py for format specification.")
```

### 4. `vectordb/__init__.py` (~+3 lines)

Export `extract_machine_block`, `validate_machine_block`, `generate_machine_block`.

---

## The Machine Block Format

### YAML inside HTML comment

```yaml
<!-- FORGE_OS_MACHINE_BLOCK_START
version: 2
decisions:
  - id: D001
    text: "Use PostgreSQL for storage"
    tier: 0.8
    rationale: "Mature, reliable, strong JSONB support"
    dependencies: []
    turn: 3
  - id: D002
    text: "No ORM, raw SQL with parameterized queries"
    tier: 0.7
    rationale: "Full control, better performance"
    dependencies: [D001]
    turn: 5
threads:
  - id: T001
    title: "Token rotation strategy"
    status: open
    priority: medium
    blocked_by: [D031]
  - id: T002
    title: "GCP deployment checklist"
    status: resolved
    resolution: "Completed - deployed to Cloud Run"
artifacts:
  - id: A001
    name: "architecture_diagram.md"
    type: diagram
metadata:
  compression_tag: "forge-os-2026-02-10"
  project: "Forge OS"
  source_conversation: "abc-123-def-456"
  turns: 42
  previous_session: "forge-os-2026-02-08"
FORGE_OS_MACHINE_BLOCK_END -->
```

### Why HTML comment?

- Invisible in rendered markdown (GitHub, Obsidian, Claude UI)
- No interference with human-readable content
- Easy to extract with simple string search (no regex needed for the block itself)
- YAML parsing inside the block is robust (not regex-dependent)

### Why YAML inside (not JSON)?

- Human-editable if needed
- Multi-line strings are natural
- Consistent with the YAML fallback format already in `sync_compression.py`

---

## Implementation Phases

### Phase A: Schema module

1. Create `vectordb/archive_schema.py` with extract, validate, generate
2. Export from `vectordb/__init__.py`

**Depends on:** Nothing

### Phase B: Parser integration

1. Update `parse_archive()` in `sync_compression.py` to try machine block first
2. Add validation warnings on parse failure

**Depends on:** Phase A

### Phase C: Generation support

1. Add `generate_machine_block()` for use in compression workflows
2. Update `prepare_compression.py` to include machine block reminder

**Depends on:** Phase A

### Phase D: Compression skill update (external)

1. Update the `compress --lossless` skill prompt to include machine block generation
2. Provide `generate_machine_block()` output format as reference

**Depends on:** Phase C. This is external to the codebase (Claude Project skill).

```
Phase A ──┬── Phase B
           └── Phase C ── Phase D (external)
```

---

## Key Design Decisions

### Machine block is supplementary, not replacement

The human-readable markdown remains primary. The machine block duplicates the structured data in a strict format. If the machine block is missing (older archives), regex parsing still works. This is a progressive enhancement, not a breaking change.

### Validation is advisory, not blocking

If `validate_machine_block()` finds errors, it prints warnings but still attempts to use the data. Only completely unparseable blocks fall through to regex. This prevents the "new format breaks old archives" failure mode.

### Schema versioning

The `version` field enables forward-compatible changes. `upgrade_schema()` handles transformations (e.g., version 1 used `confidence` instead of `tier`).

---

## Verification

```bash
# Phase A: Schema module
python -c "
from vectordb.archive_schema import generate_machine_block, extract_machine_block, validate_machine_block

# Generate
block = generate_machine_block(
    decisions=[{'id': 'D001', 'text': 'Test decision', 'tier': 0.8}],
    threads=[{'id': 'T001', 'title': 'Test thread', 'status': 'open'}],
    metadata={'compression_tag': 'test-tag', 'project': 'Test'},
)
print(block[:200])

# Round-trip: generate → extract → validate
full_archive = f'# Test Archive\n\nSome content...\n\n{block}\n'
parsed = extract_machine_block(full_archive)
errors = validate_machine_block(parsed)
print(f'Errors: {len(errors)}')
assert len(errors) == 0, f'Unexpected errors: {errors}'
print('Round-trip passed')
"
```

---

## File Size Estimates

| File | Lines | Action |
|------|-------|--------|
| `vectordb/archive_schema.py` | ~150 | Create |
| `scripts/sync_compression.py` | +30 | Modify |
| `scripts/prepare_compression.py` | +15 | Modify |
| `vectordb/__init__.py` | +3 | Modify |
| **Total** | **~198** | |
