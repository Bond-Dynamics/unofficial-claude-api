# Plan: Automatic Priming Block Activation in Continuation Pipeline

## Problem

Priming blocks are compiled by the expedition-compiler skill and stored in `priming_registry` with embedded territory keys. But activation is manual — someone has to remember the block exists and paste it into the right conversation. The whole point of priming is push-based: context that finds you when you enter relevant territory, not context you have to pull.

## Goal

When `prepare_continuation.py` assembles context for a new session, it should automatically query the priming registry for blocks whose territory keys match the project and inject them into the continuation context. When `prepare_compression.py` runs before compressing, it should surface pending expedition flags so they don't get lost.

## Current Flow

```
prepare_continuation.py --project "Forge OS"
  → queries: active_decisions, active_threads, stale items, lineage
  → outputs: Decisions In Force, Open Threads, Warnings, Lineage
  → copies to clipboard
```

## Proposed Flow

```
prepare_continuation.py --project "Forge OS" [--topic "attention gauge field"]
  → queries: active_decisions, active_threads, stale items, lineage
  → NEW: queries priming_registry for active blocks matching project
  → NEW: if --topic provided, runs find_relevant_priming() for semantic match
  → NEW: queries expedition_flags for pending flags (awareness)
  → outputs: Decisions In Force, Open Threads, Warnings, Lineage,
             PRIMING BLOCKS, PENDING FLAGS
  → copies to clipboard

prepare_compression.py --project "Forge OS"
  → existing: active_threads, stale items, conflicts
  → NEW: queries expedition_flags for pending flags (reminder to compile)
  → outputs: Active Threads, Stale Warnings, Conflict Alerts,
             PENDING EXPEDITION FLAGS
```

## Changes

### 1. `scripts/prepare_continuation.py`

**Add imports:**
```python
from vectordb.expedition_flags import get_pending_flags
from vectordb.priming_registry import find_relevant_priming, list_priming_blocks
```

**Add `--topic` argument** to CLI parser:
```python
parser.add_argument(
    "--topic",
    help="Topic text for semantic priming block activation"
)
```

**In `assemble_continuation_context()`:**

Add `topic=None` parameter.

After the Lineage section, add two new sections:

**Priming Blocks section:**

1. Always query `list_priming_blocks(project, db=db)` to get all active blocks for the project
2. If `topic` is provided, also run `find_relevant_priming(topic, project=project, db=db)` and merge results (dedup by UUID)
3. For each matched priming block:
   - Print territory name, confidence floor, source expeditions
   - Print the content (truncated to first 400 words to avoid noise)
   - Print territory keys for transparency
4. If no blocks matched, print `- (no priming blocks for this project)`

Format:
```markdown
### Priming Blocks

#### PRIMING: Cloud Infrastructure for Non-Developer Builders
**Territory Keys:** cloud, PaaS, infrastructure, Firebase
**Confidence Floor:** 0.3
**Source:** EXP-001

[Content — first 400 words of the priming block]

---
```

**Pending Flags section:**

1. Query `get_pending_flags(project, db=db)`
2. Group by category
3. For each flag, print description and conversation source
4. This serves as awareness — the user sees what's been flagged but not yet compiled

Format:
```markdown
### Pending Expedition Flags (3 uncompiled)

**Inversions:**
- "Configuration is guardrails, not freedom" (from session bc76c40c...)

**General:**
- "Permission architecture maps to builder tools" (from session 43589b84...)
```

**Update summary line:**
```python
f"**Summary:** {len(active_decisions)} decisions in force, "
f"{len(active_threads)} open threads, "
f"{len(stale_decisions) + len(stale_threads)} stale items, "
f"{len(lineage)} lineage hops, "
f"{len(priming_blocks)} priming blocks, "
f"{len(pending_flags)} pending flags"
```

### 2. `scripts/prepare_compression.py`

**Add import:**
```python
from vectordb.expedition_flags import get_pending_flags
```

**In `assemble_compression_context()`:**

After the Conflict Alerts section, add:

**Pending Expedition Flags section:**
1. Query `get_pending_flags(project, db=db)`
2. If flags exist, list them as a reminder to compile before compressing
3. This prevents flags from being silently dropped during compression

Format:
```markdown
### Pending Expedition Flags
- WARNING: 3 uncompiled flags. Run "compile expedition" or "compile flagged"
  before compressing to avoid losing flagged findings.
- [inversion] "Configuration is guardrails" (from bc76c40c...)
- [general] "Permission architecture" (from 43589b84...)
```

**Update summary line** to include flag count.

### 3. `scripts/forge_session.sh`

**Add `flags` command:**
```bash
flags     --project X              Show pending expedition flags
```

Implementation:
```bash
cmd_flags() {
    python3 "$SCRIPT_DIR/show_flags.py" --project "$project"
}
```

**Add `compile` command:**
```bash
compile   --project X              Show flagged items for compilation
```

This is a convenience wrapper — it shows pending flags grouped by category so the user can feed them to the expedition-compiler skill.

**Update `full` workflow** to include a pre-compression flag check:
Between Step 2 (prepare compression) and Step 3 (sync archive), check if there are pending flags and warn the user.

### 4. `scripts/show_flags.py` (new, ~60 lines)

Simple CLI that queries `get_pending_flags()` and `get_flags_by_category()`, formats them for display. Grouped by category, with conversation source and timestamp.

**CLI:**
```
python scripts/show_flags.py --project "Forge OS"
python scripts/show_flags.py --project "Forge OS" --category inversion
```

### 5. Tests

**`tests/test_prepare_continuation.py`** (new, ~40 lines):
- Test that priming blocks appear in output when present
- Test that `--topic` triggers semantic search
- Test that pending flags appear in output
- Test that empty priming/flags produce "(none)" markers
- Mock all registry calls

**`tests/test_prepare_compression.py`** (new, ~20 lines):
- Test that pending flags warning appears in output
- Test that empty flags produce no warning section

## Content Truncation Strategy

Priming blocks can be long. To prevent continuation context from exploding:

1. **Per-block limit:** First 400 words of content (matching the priming block schema's recommendation)
2. **Total priming limit:** If more than 3 blocks match, show the top 3 by relevance score (if topic-matched) or most recently updated (if project-only)
3. **Flag limit:** Show at most 10 pending flags in the continuation context, with a count of remaining

## Files Changed

| File | Action | Lines |
|------|--------|-------|
| `scripts/prepare_continuation.py` | Edit | +60 |
| `scripts/prepare_compression.py` | Edit | +25 |
| `scripts/forge_session.sh` | Edit | +30 |
| `scripts/show_flags.py` | Create | ~60 |
| `tests/test_prepare_continuation.py` | Create | ~40 |
| `tests/test_prepare_compression.py` | Create | ~20 |

## Verification

1. Plant some test flags:
```python
from vectordb.expedition_flags import plant_flag
from vectordb.uuidv8 import project_id

proj = project_id("Forge OS", 1707350400000)
plant_flag("Configuration is guardrails", "Forge OS", proj, "867d23c5-52a9-47f9-8280-fffa7ea2dd63", category="inversion")
plant_flag("Wrapper = Value Capture pattern", "Forge OS", proj, "867d23c5-52a9-47f9-8280-fffa7ea2dd63", category="isomorphism")
```

2. Store a test priming block:
```python
from vectordb.priming_registry import upsert_priming_block

upsert_priming_block(
    territory_name="Cloud Infrastructure",
    territory_keys="cloud, PaaS, infrastructure, Firebase, vibe coding",
    content="## PRIMING: Cloud Infrastructure\n\n### Terrain Map\n\nCloud infrastructure exists in layers...",
    project="Forge OS",
    project_uuid=proj,
    source_expedition="EXP-001",
)
```

3. Run continuation and verify priming block + flags appear:
```bash
python scripts/prepare_continuation.py --project "Forge OS"
python scripts/prepare_continuation.py --project "Forge OS" --topic "cloud infrastructure PaaS"
```

4. Run compression and verify flag warning appears:
```bash
python scripts/prepare_compression.py --project "Forge OS"
```

5. Run full test suite:
```bash
python -m unittest discover -s tests -v
```
