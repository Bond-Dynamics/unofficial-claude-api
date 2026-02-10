# Lossless Compression Schema

## Architecture

```
┌─────────────────────────────────────┐
│  ACTIVE CONTEXT (in-window)         │
│  - Continuation prompt              │
│  - Inherited context (if partial)   │
│  - Recent 2-3 turns                 │
│  - Decision index (pointers only)   │
│  - Open threads                     │
└─────────────────────────────────────┘
                 │
                 │ retrieve on demand
                 ▼
┌─────────────────────────────────────┐
│  EXTERNAL STORE (full fidelity)     │
│  - Complete conversation transcript │
│  - All artifact versions            │
│  - Full rationale chains            │
│  - Chunk index for retrieval        │
│  - Prior compression archives       │
└─────────────────────────────────────┘
```

## Configuration Schema

```yaml
compression_mode: hybrid_lossless

in_context:
  max_tokens: 4000
  contains:
    - continuation_prompt: full
    - decision_index: summaries + refs
    - inherited_context: full (if partial compression)
    - recent_turns: 3
    - open_threads: full
    - last_compressed_tag: [semantic tag string]
    - last_compressed_turn_count: [turn number]

# --- PARTIAL COMPRESSION (omit entirely for full compression) ---
compression_scope:
  mode: full | partial
  turn_range: [start, end]
  scope_topic: [natural language topic filter]
  prior_compression_tag: [tag of parent compression, if any]
  context_query: [keywords or tag provided by user]

inherited_context:
  source: [exact tag | keyword match | hybrid]
  source_description: [what the inherited context represents]
  carried_decisions:
    - id: [original decision ID]
      tier: [0.0 - 1.0]
      decision: [what was decided]
      relevance: [why it matters to current scope]
  carried_constraints:
    - [constraint that carries forward]
  carried_frameworks:
    - name: [framework name]
      summary: [1-2 sentence description]
      relevance: [how it informs current scope]
# --- END PARTIAL COMPRESSION ---

external_store:
  type: [file | vector_db | conversation_memory]
  location: [filepath or identifier]
  contains:
    - full_transcript: true
    - artifact_versions: all
    - rationale_chains: full
    - prior_compressions: [list of prior compression tags and their archive locations]

retrieval_triggers:
  - pattern: "Why did we decide X?"
    action: fetch rationale chunk
  - pattern: "Show me the earlier version"
    action: fetch artifact history
  - pattern: "What did we discuss about Y?"
    action: semantic search transcript
  - pattern: "What was in the [tag/keywords] compression?"
    action: fetch prior compression archive
  - pattern: "Show inherited context for this session"
    action: display inherited_context block
```

## Three-Component Output

### Component 1: Continuation Prompt

```markdown
## CONTINUATION PROMPT (LOSSLESS)

### Session Reference
- Session ID: [unique identifier]
- Archive Location: [filepath]
- Decisions Made: [count]
- Artifacts Produced: [count]
- Last Compressed Tag: [tag string]
- Last Compressed Turn: [turn number]
- Last Updated: [timestamp]
- Compression Scope: [full | partial (turns N-M)]
- Inherited From: [prior tag or "none"]

### Foundational Context (partial compression only)
[Inherited decisions, frameworks, and constraints from prior compression
or earlier conversation. Presented as established facts, not references.]

### Compressed State
[Problem definition, decisions summary, constraints, open threads]

### Decision Index
| ID | Decision | Rationale (compressed) | Source | Ref |
|----|----------|------------------------|--------|-----|
| D001 | [decision] | [1-line rationale] | inherited / this session | chunk_001 |

### Current Artifact State
[Most recent version or summary + reference]

### Retrieval Protocol
[Available retrieval commands - see below]

### Immediate Next Action
[What the new context should do first]
```

### Component 2: Conversation Archive

```markdown
# Conversation Archive: [session_id]

## Metadata
- Created: [timestamp]
- Turns: [count]
- Compressed Turn Range: [start-end, or "all"]
- Primary Topic: [topic]
- Final Status: [completed | paused | branched]
- Last Compressed Tag: [tag string]
- Prior Compression Chain: [list of prior tags in order, if any]

## Compression Lineage (partial compression only)
| Order | Tag | Turn Range | Relationship |
|-------|-----|------------|-------------|
| 1 | TOPIC_A_RESULT | 1-20 | Parent |
| 2 | MATH_CODEBREAKER_BRIDGE | 21-35 | Current (inherits from #1) |

## Inherited Context Snapshot
[Full inherited_context block as it was at compression time, for audit trail]

## Full Transcript
[All turns within compression scope, with full content]
[For partial: turns outside scope are excluded but referenced in lineage]

## Transcript Range Markers
[Markers indicating which turns belong to which topic cluster,
enabling future partial compressions to quickly identify relevant ranges]
| Range | Topic Cluster | Key Decisions |
|-------|---------------|---------------|
| 1-8 | Problem definition and exploration | D001, D002 |
| 9-15 | Framework development | D003, D004 |
| 16-20 | Iteration and refinement | D005 |
| 21-28 | Math curriculum design | D010, D011 |
| 29-35 | Codebreaker integration | D012 |

## Decision Log (Full Detail)
[All decisions per decision log schema - see below]

## Artifact History
[All artifacts per artifact history schema - see below]

## Chunk Index
| Chunk ID | Turn Range | Topic | Decisions | Scope |
|----------|------------|-------|-----------|-------|
| chunk_001 | 1-3 | Problem definition | D001 | inherited |
| chunk_005 | 21-25 | Math curriculum | D010, D011 | this session |
```

### Component 3: Retrieval Instructions

```markdown
## RETRIEVAL PROTOCOL

This session continues from a previous conversation.
Compressed state is in-context. Full archive available externally.

### Compression Lineage
This session inherits from: [list of prior compression tags]
Compressed scope: turns [N] through [M]

### Available Commands
| Pattern | Action |
|---------|--------|
| "Why did we decide [X]?" | Fetch full rationale from decision log |
| "What were the alternatives for [X]?" | Fetch alternatives_rejected |
| "Show earlier version of [artifact]" | Fetch from artifact history |
| "What did we discuss about [topic]?" | Search transcript |
| "Expand on [compressed statement]" | Find source, provide full context |
| "What was in the [tag] compression?" | Fetch prior compression archive |
| "Show what I inherited from [tag]" | Display inherited_context snapshot |
| "What turns cover [topic]?" | Consult transcript range markers |

### Response Format
## Retrieved Context: [what was requested]

**Source:** [chunk_id | decision_id | artifact_version | prior_compression_tag]
**Transcript Reference:** Turn [N] - Turn [M]
**Scope:** [inherited | this session]

[Full retrieved content]

---
*Continuing with current task...*
```

## Decision Log Schema

```yaml
decisions:
  - id: D001
    tier: [0.0 - 1.0]
    timestamp: [ISO 8601]
    turn: [conversation turn number]
    scope: [inherited | this_session]  # tracks provenance
    inherited_from: [prior compression tag, if inherited]
    decision: [full decision statement]
    context: [what prompted this decision]
    rationale: [complete reasoning]
    confidence: [high | medium | low]
    alternatives_considered:
      - option: [alternative A]
        reason_rejected: [why not chosen]
      - option: [alternative B]
        reason_rejected: [why not chosen]
    dependencies: []  # prior decisions this builds on
    dependents: []    # later decisions that depend on this
    full_context_ref: [chunk_id or turn range]
```

## Artifact History Schema

```yaml
artifacts:
  - id: A001
    name: [artifact name]
    type: [code | schema | prompt | analysis | document]
    created: [turn number]
    scope: [inherited | this_session]

    versions:
      - version: 1
        created_turn: [turn number]
        status: [draft | superseded | final]
        changes_from_previous: null
        content: |
          [full artifact content]

      - version: 2
        created_turn: [turn number]
        status: [draft | superseded | final]
        changes_from_previous: [what changed and why]
        triggered_by: [D002]
        content: |
          [full artifact content]

    current_version: 2
    final: false
```

## Integrity Check Protocol

If user questions a decision that contradicts archived state:

1. Acknowledge the apparent contradiction
2. Retrieve relevant context from archive (check both current and inherited)
3. Present both current understanding and archived rationale
4. Ask user to confirm which should govern going forward
5. Update decision log if decision is revised

If user questions inherited context accuracy:

1. Retrieve the original compression's `inherited_context` snapshot
2. Compare against the source compression's full archive if available
3. Flag any drift or loss and let user correct

## Quality Gate

- [ ] Full transcript captured in archive (within compression scope)
- [ ] All decisions indexed with full rationale AND tier assignment
- [ ] All artifact versions preserved with change notes
- [ ] Chunk index complete for retrieval
- [ ] Retrieval protocol included in continuation prompt
- [ ] Session ID consistent across all outputs
- [ ] Tag generated per protocol
- [ ] Epistemic tiers assigned to all archived decisions

### Additional for Partial Compression
- [ ] `compression_scope` populated with mode, turn range, and context reference
- [ ] `inherited_context` includes only relevant carried decisions/constraints/frameworks
- [ ] Compression lineage table documents the full chain
- [ ] Transcript range markers present for future partial compression use
- [ ] Inherited decisions marked with `scope: inherited` in decision log
- [ ] Continuation prompt has distinct "Foundational Context" section
- [ ] `inherited_context` snapshot preserved in archive for audit trail
