---
name: context-compression
description: Preserve conversation state across context windows for seamless continuation. Triggered by "compress", "save state", "summarize for continuation", "execute transmutation script" (lossy mode), or "--lossless" / "archive this conversation" (lossless mode). Supports partial compression with context bridging via "compress recent, bridge from [keywords]" or bash-style flags. Use when conversations hit 15+ turns, produce complex artifacts, or need state transfer to new sessions.
---

# Context Compression

Compress conversation state into portable continuation prompts that preserve decisions, constraints, and open threads while discarding deliberation and tangents.

**Core insight:** Conversations are stateful programs. Compression persists state across execution contexts.

## Modes

| Mode | Trigger | Output | Use When |
|------|---------|--------|----------|
| **Lossy** | "compress", "save state", "transmutation script" | YAML state + continuation prompt | Short continuations, clear decisions |
| **Lossless** | "--lossless", "archive this conversation" | Continuation + full archive + retrieval protocol | Long projects, audits, complex branching |
| **Partial** | "compress recent, bridge from [keywords]", bash-style flags (see below) | Scoped YAML state + inherited context + continuation prompt | Mid-conversation compression, layered sessions, topic branching |

## Trigger Syntax

### Natural Language Triggers

All existing triggers remain valid. Partial compression adds:

- `"compress recent, bridge from [tag or keywords]"` — compress recent turns, inheriting relevant context from prior compression or earlier conversation matching the keywords
- `"compress from [topic A] through [topic B]"` — compress a conceptual range
- `"compress [topic], pull in [earlier topic]"` — compress a specific thread with context inheritance

### Bash-Style Triggers

Flexible flag-based syntax. **No flag is required** — omit any flag and the system infers from conversation context.

```
compress [--lossy | --lossless] [--turns N-M] [--context <tag | keywords>] [--scope <topic>]
```

| Flag | Purpose | Accepts | Default if omitted |
|------|---------|---------|-------------------|
| `--lossy` / `--lossless` | Compression mode | (flag only) | `--lossy` |
| `--turns N-M` | Turn range to compress | Range (e.g., `16-35`) or `recent` | All turns since last compression |
| `--context` | Prior context to bridge in | Exact tag (e.g., `ATTENTION_CONSCIOUSNESS_FRAMEWORK`) OR fuzzy keywords (e.g., `attention consciousness`, `math program`) | None — full compression, no inheritance |
| `--scope` | Topic filter | Natural language topic description | Entire turn range |

**Examples:**
```
compress --lossless --turns 16-35 --context attention consciousness
compress --turns recent --context ATTENTION_CONSCIOUSNESS_FRAMEWORK
compress --lossy --scope "math curriculum for veterans" --context consciousness physics
compress --context "the attention theory stuff"
compress --lossless --turns 21-35 --context attention framework --scope math program
```

**Keyword resolution:** When `--context` receives keywords instead of an exact tag, resolve by:
1. Check `last_compressed_tag` from any prior compression in the session — match against tag components
2. Scan conversation history for topic clusters matching the keywords
3. If ambiguous, present candidate matches and ask user to confirm

## Compression Priority

Preserve in this order:

| Priority | Content | Action |
|----------|---------|--------|
| 1 - Critical | Final decisions, constraints, open threads | Never compress |
| 2 - High | Decision rationale, rejected alternatives | Compress to 1-2 sentences |
| 3 - Medium | Iteration history, intermediate artifacts | Summarize pattern only |
| 4 - Low | Deliberation, tangents, pleasantries | Discard |

## Continuation Prompt Requirements

The continuation prompt MUST be:
- **Self-sufficient** — assume new context has ZERO prior history
- **Explicit** — no implicit references ("as discussed" → state the decision)
- **Actionable** — open threads stated as concrete next steps
- **Decision-preserving** — include rationale to prevent re-litigation
- **Layered** (partial mode) — inherited context appears as a distinct "Foundational Context" section BEFORE current-session decisions

## Epistemic Tiering

Assign confidence tier (0.0-1.0) to each decision:

| Tier | Range | Criteria | In Continuation |
|------|-------|----------|-----------------|
| Validated | 0.8-1.0 | Tested, documented best practice | Include as fact |
| Heuristic | 0.3-0.7 | Works in practice, mechanism unclear | Include as guidance |
| Speculative | 0.0-0.2 | Untested hypothesis | Archive only, exclude |

See `references/epistemic-tiers.md` for assignment guidelines.

## Tag Generation

Generate `last_compressed_tag` as: `[CONCEPT]_[DETAIL]_[RESULT]`

Examples: `API_VERSION_V7_FINALIZED`, `TENANT_PATH_URL_DECISION`, `USER_SCHEMA_LOCKED`

For partial compressions, append scope: `MATH_CURRICULUM_CODEBREAKER_BRIDGE`

## Partial Compression

Partial compression handles the case where you need to compress a **subset** of the conversation while selectively inheriting context from earlier turns or prior compressions.

### When to Use

- A conversation has already been compressed, and new work has been done that needs its own compression
- You want to compress a specific topic thread without capturing unrelated discussion
- You need to bridge context from an earlier part of the conversation (or a prior compression) into a new compression without re-compressing everything

### How It Works

```
[Turns 1-20: Topic A]
    ↓ COMPRESSED (tag: TOPIC_A_RESULT)
[Turns 21-30: Topic B, informed by Topic A]
[Turns 31-35: Topic C, connects B to new domain]
    ↓ PARTIAL COMPRESS (turns 21-35, bridge from TOPIC_A_RESULT)
      → Produces: inherited context from Topic A + compressed state of turns 21-35
```

### Inherited Context Resolution

When `--context` is provided as keywords rather than an exact tag:

1. **Exact tag match** — if keywords match a `last_compressed_tag`, pull from that compression's decisions and constraints
2. **Keyword scan** — search conversation turns outside the compression scope for topic clusters matching the keywords; extract relevant decisions, frameworks, and constraints
3. **Hybrid** — combine both: pull from a prior compression AND add specific uncompressed context that matches
4. **Ambiguity handling** — if multiple candidate contexts match, present them to the user as options before proceeding

### Inherited Context Filtering

Not everything from prior context is relevant. Apply this filter:

| Include | Exclude |
|---------|---------|
| Decisions that the current scope depends on or extends | Decisions unrelated to current scope |
| Frameworks/models that inform current work | Implementation details from prior scope |
| Constraints that carry forward | Resolved issues from prior scope |
| Terminology/definitions needed for continuity | Deliberation and iteration from prior scope |

### Quality Gate (Partial)

- [ ] `compression_scope` populated with mode, turn range, and context reference
- [ ] `inherited_context` includes only decisions/constraints relevant to current scope
- [ ] Continuation prompt has distinct "Foundational Context" and "Current Session" sections
- [ ] Inherited decisions are attributed to their source tag/keywords
- [ ] No implicit references to uncompressed context
- [ ] New tag reflects the combined scope (e.g., `MATH_CODEBREAKER_BRIDGE`)

## Lossy Compression

Output YAML state block + self-contained continuation prompt.

**Schema:** See `references/lossy-schema.md` for full YAML template.

**Quality Gate:**
- [ ] Continuation prompt readable without ANY prior context
- [ ] No implicit references
- [ ] Decisions include rationale
- [ ] Open threads explicitly actionable
- [ ] All decisions assigned epistemic tier
- [ ] Tier 3 content excluded from continuation
- [ ] Tag generated per protocol

## Lossless Compression

Output three components:
1. **Continuation prompt** — compressed state + decision index + retrieval commands
2. **Full archive** — complete transcript, all artifact versions, full rationale chains
3. **Retrieval protocol** — commands for on-demand context fetch

**Schema:** See `references/lossless-schema.md` for full templates.

**Retrieval triggers:**
| Pattern | Action |
|---------|--------|
| "Why did we decide X?" | Fetch rationale chunk |
| "Show earlier version" | Fetch artifact history |
| "What did we discuss about Y?" | Search transcript |

## Emergency Compression

If context limit approaching:
1. Immediately trigger lossy compression
2. Output continuation prompt
3. Instruct user to start new session with prompt

**Warning signs:** 15+ turns, multiple artifacts, significant iteration.
