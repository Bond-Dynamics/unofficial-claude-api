# Local LLM Migration Path

**Date:** 2026-02-08
**Status:** Architecture planning
**References:** forge-os-architecture.md, context-rot-assessment.md, Cheeky UUIDv8 implementation
**Core principle:** Claude is the stopgap. Forge OS runs on any LLM. The migration must be seamless.

---

## The Goal

Forge OS currently uses Claude as its knowledge engine — conversations happen in Claude's UI, the compression skill runs inside Claude's context window, and `fetch_conversations.py` pulls data from Claude's API. None of this is permanent. The target architecture runs a local LLM as the knowledge engine, with no dependency on Anthropic's infrastructure, API, or pricing.

The migration is not "port Forge OS from Claude to something else." It's "Forge OS is a system that happens to use Claude right now, and the interface is designed so the LLM is a swappable component."

---

## Current Claude Dependencies

Every Claude dependency falls into one of three categories: **already decoupled**, **decoupled by design** (just needs the swap), or **hard dependency** (needs architectural work).

### Already Decoupled (no migration work needed)

| Component | Current | Why It's Independent |
|-----------|---------|---------------------|
| VectorDB (MongoDB) | Local MongoDB | Pure persistence layer. No Claude API calls. |
| Embeddings | VoyageAI | Separate API, separate model. Swappable to local embedding model. |
| UUIDv8 ID system | Pure computation | SHA-256 + timestamp. No LLM involved. |
| Pre/post scripts | Python scripts | `prepare_compression.py`, `sync_compression.py`, `prepare_continuation.py` — pure Python, query MongoDB directly. |
| Pipeline (`pipeline.py`) | Python + VoyageAI | Classifier is rule-based regex. Embeddings are VoyageAI batch calls. No Claude dependency. |
| Content classifier | Rule-based regex | `classifier.py` uses pattern matching, not LLM inference. |
| Pattern store/match | VoyageAI + MongoDB | Embedding similarity search. Model-agnostic. |
| Scratchpad, archive, events | MongoDB collections | TTL key-value store, retention policies, audit log. Pure database operations. |

### Decoupled by Design (swap the LLM, everything else stays)

| Component | Current Implementation | What Changes | What Stays |
|-----------|----------------------|-------------|------------|
| Compression skill | Prompt specification executed by Claude | Prompt sent to local LLM instead | The YAML schema, epistemic tiers, archive format, retrieval protocol — all survive unchanged |
| Continuation consumption | User pastes archive into Claude conversation | Archive fed to local LLM as system/user prompt | The archive format, inherited context structure, foundational context section — all survive |
| Decision-making | Claude reasons and produces D001, D002, etc. | Local LLM reasons and produces same structured output | Decision schema, tier assignment, conflict detection — all survive |
| Code generation | Claude writes code in conversation | Local LLM writes code | Quality varies by model, but the interface is identical: prompt in, code out |
| Thread tracking | Claude marks T001 as OPEN/RESOLVED in archive | Local LLM marks same fields | Thread schema unchanged |

The compression skill is a **protocol specification**, not a Claude feature. It defines WHAT to compress (decisions, threads, artifacts, constraints), HOW to structure it (YAML state block, continuation prompt, archive), and WHAT to preserve (priority-ordered: critical > high > medium > low). Any LLM that can follow structured instructions and produce YAML can execute this protocol.

### Hard Dependencies (need architectural work)

| Dependency | Why It's Hard | Migration Path |
|-----------|--------------|----------------|
| Claude's conversation UI | Conversations happen in claude.ai — the browser is the interface | Replace with local chat UI (see below) |
| Claude's API for sync | `fetch_conversations.py` uses Claude's internal API + Firefox cookies to pull conversation history | Replace with local conversation storage — conversations are saved locally, no API fetch needed |
| Claude's context window management | Claude handles tokenization, context limits, message history internally | Local LLM runtime (llama.cpp, vLLM, Ollama) handles this — different limits, different tokenizers |
| Claude Code (CLI tool) | Task tool, agent spawning, skill system run through Claude Code's infrastructure | Replace with local agent orchestration (claude-flow CLI already handles coordination — the execution layer needs a local LLM backend) |

---

## The Abstraction Layer

The migration requires one new abstraction: a **knowledge engine interface** that Forge OS talks to, with Claude and local LLMs as interchangeable implementations.

```
Forge OS
  │
  ├─ Compression Protocol (YAML schema, epistemic tiers, archive format)
  │    └─ Protocol-level: LLM-agnostic. Any model that follows the spec.
  │
  ├─ Knowledge Engine Interface
  │    ├─ generate(prompt, schema?) → structured output
  │    ├─ compress(conversation_state) → archive
  │    ├─ continue(archive + context) → resumed session
  │    ├─ decide(context, options) → decision with tier + rationale
  │    └─ embed(text) → vector  (already abstracted via VoyageAI)
  │
  ├─ Implementation: Claude (current)
  │    ├─ generate() → Claude API / Claude Code
  │    ├─ compress() → compression skill in Claude's context window
  │    ├─ continue() → paste archive into new Claude conversation
  │    ├─ decide() → Claude reasons in conversation
  │    └─ embed() → VoyageAI API
  │
  └─ Implementation: Local LLM (target)
       ├─ generate() → llama.cpp / vLLM / Ollama API
       ├─ compress() → same skill prompt sent to local model
       ├─ continue() → archive loaded as system prompt in local session
       ├─ decide() → local model reasons with same prompt structure
       └─ embed() → local embedding model (nomic-embed, bge, etc.)
```

The interface is narrow: `generate`, `compress`, `continue`, `decide`, `embed`. Everything else — the vectordb, the graph, the UUIDv8 IDs, the pre/post scripts, the pipeline, the classifier — operates below this interface and is already LLM-agnostic.

---

## What Survives the Migration Unchanged

These components are **permanent infrastructure** — they don't change when the LLM changes:

1. **MongoDB vectordb** — all collections (messages, conversations, documents, patterns, scratchpad, archive, events, lineage, threads, decisions)
2. **UUIDv8 ID system** — deterministic derivation from `BASE_UUID` through project namespaces to entities
3. **Compression protocol** — YAML schema, epistemic tiers, archive format, retrieval protocol, partial compression, `--context` bridging
4. **Graph structure** — lineage DAG, thread registry, decision registry with `conflicts_with` edges
5. **Conflict resolution policy** — auto-resolve trivial, surface ambiguous, block cross-project
6. **Content classifier** — rule-based regex, no LLM calls
7. **Pre/post scripts** — `prepare_compression.py`, `sync_compression.py`, `prepare_continuation.py`
8. **Pipeline** — conversation ingestion, embedding, enrichment, lineage detection
9. **Pattern store** — merge logic, confidence scoring, retrieval counting
10. **Decay detection** — `last_validated` timestamps, hop counting, revalidation flagging

This is by design. The architecture separates the **reasoning engine** (swappable LLM) from the **memory system** (permanent vectordb + graph). The LLM is stateless — it processes prompts and produces outputs. The vectordb is stateful — it persists decisions, tracks lineage, detects conflicts. Swapping the LLM doesn't touch the state.

---

## Migration Phases

### Phase 0: Abstraction (do now, while still on Claude)

Create the knowledge engine interface as a Python module. All Forge OS tooling calls through this interface, never directly to Claude's API.

```python
# vectordb/engine.py

class KnowledgeEngine:
    """Abstract interface for the reasoning engine."""

    def generate(self, prompt: str, schema: dict | None = None) -> str:
        """Generate a response, optionally constrained to a JSON/YAML schema."""
        raise NotImplementedError

    def compress(self, conversation_state: dict) -> dict:
        """Execute the compression protocol on a conversation state."""
        raise NotImplementedError

    def embed(self, text: str) -> list[float]:
        """Generate an embedding vector for text."""
        raise NotImplementedError


class ClaudeEngine(KnowledgeEngine):
    """Current implementation: Claude API."""
    ...


class LocalEngine(KnowledgeEngine):
    """Target implementation: local LLM via llama.cpp / vLLM / Ollama."""
    ...
```

This is a thin wrapper. The goal is not to build a framework — it's to ensure no Forge OS code has a hard import of `anthropic` or calls Claude's API directly except through this interface.

### Phase 1: Embedding Independence

Swap VoyageAI for a local embedding model. This is the lowest-risk, highest-value migration step.

| Current | Target | Why |
|---------|--------|-----|
| VoyageAI `voyage-3-large` (1024d) | `nomic-embed-text` or `bge-large-en-v1.5` (1024d or 768d) | Eliminates API dependency, runs on-device, zero marginal cost |

**Constraints:**
- Must match dimensionality of existing embeddings (1024d) OR re-embed all 3,777 messages + 222 conversations. Re-embedding is ~400 VoyageAI batch calls currently; with a local model, it's free but slower.
- If dimensionality changes (e.g., 768d), all vector search indexes must be rebuilt.
- Quality tradeoff: VoyageAI is best-in-class. Local models are close but not identical. Test retrieval quality before committing.

**Approach:**
1. Run both models in parallel on a sample of 100 queries
2. Compare top-5 retrieval overlap (Jaccard similarity)
3. If overlap > 0.8, swap. If not, consider keeping VoyageAI for initial embedding and local for real-time queries.

### Phase 2: Conversation Storage

Replace Claude's conversation API with local conversation persistence. This eliminates the `fetch_conversations.py` → Claude API dependency entirely.

| Current | Target |
|---------|--------|
| Conversations happen in claude.ai, fetched weekly by sync cron | Conversations happen locally, saved directly to MongoDB |
| `fetch_conversations.py` uses Firefox cookies + Claude's internal API | Local chat interface writes conversation turns directly to `message_embeddings` |
| Conversation UUIDs come from Claude's API | Conversation UUIDs derived via UUIDv8 at creation time |

**What this requires:**
- A local chat interface (terminal UI, web UI, or API server) that talks to the local LLM
- Conversation persistence: each turn saved to MongoDB as it happens (no batch sync needed)
- Real-time embedding: embed each message as it's produced (local embedding model makes this free)
- Real-time lineage: when a compression archive is detected in conversation output, register lineage edges immediately (no retroactive detection needed)

**What this enables:**
- No more weekly sync delay — the graph updates in real-time
- No more Firefox cookie management
- No more 403 errors on restricted conversations
- Conversations are always available locally, even offline
- UUIDv8 IDs are assigned at creation, not during sync

### Phase 3: Local LLM as Reasoning Engine

Replace Claude as the model that executes the compression skill, makes decisions, and generates code.

**Minimum model requirements:**

| Capability | Minimum | Preferred | Why |
|-----------|---------|-----------|-----|
| Context window | 8K tokens | 32K+ tokens | Compression archives can be 2,000-12,000+ chars. Lossless mode needs room for the full archive + continuation prompt. |
| Structured output | YAML parsing | JSON mode / function calling | The compression protocol produces YAML state blocks. The model must reliably output structured data. |
| Instruction following | Basic | Strong | The compression skill is a multi-page prompt specification. The model must follow it precisely. |
| Code generation | Functional | Production-quality | Forge OS is a development tool. The LLM must write good code. |
| Reasoning | Chain-of-thought | Extended thinking | Epistemic tier assignment and conflict detection require genuine reasoning, not pattern matching. |

**Candidate local models (as of 2026):**

| Model | Parameters | Context | Structured Output | Notes |
|-------|-----------|---------|-------------------|-------|
| Llama 3.3 70B | 70B | 128K | Good | Strong all-around, fits on 2x 24GB GPUs |
| Qwen 2.5 72B | 72B | 128K | Excellent | Best structured output, strong reasoning |
| DeepSeek V3 | 671B MoE (37B active) | 128K | Good | MoE makes it runnable on consumer hardware |
| Mistral Large | 123B | 128K | Excellent | Strong instruction following |
| Command R+ | 104B | 128K | Excellent | Built for RAG, good retrieval augmentation |

**Quantization:** 4-bit GGUF quantization (Q4_K_M) reduces memory requirements ~4x with <5% quality loss for structured output tasks. A 70B model at Q4 fits in ~40GB VRAM (2x RTX 3090/4090 or 1x A100).

**Runtime options:**
- `llama.cpp` — C++ inference, supports GGUF, runs on CPU+GPU, OpenAI-compatible API server
- `vLLM` — Python inference, supports PagedAttention for efficient batching, best throughput
- `Ollama` — Simplified wrapper around llama.cpp, easiest setup, good for single-user

### Phase 4: Agent Orchestration

Replace Claude Code's Task tool and agent spawning with local orchestration.

| Current | Target |
|---------|--------|
| Claude Code spawns agents via Task tool | claude-flow CLI spawns agents that call local LLM |
| Each agent is a Claude API call | Each agent is a local LLM inference call |
| Agent coordination via claude-flow MCP | Same — claude-flow coordination is already LLM-agnostic |

claude-flow's coordination layer (swarm init, agent spawn, memory store/search, hooks) is already independent of Claude. The only Claude dependency is that the **agents themselves** are Claude API calls via the Task tool. Swapping this means:

1. claude-flow agent definitions get a `model_backend` field: `claude` | `local`
2. Agent execution calls the knowledge engine interface instead of Claude's API
3. Background workers (`optimize`, `audit`, `testgaps`, etc.) run against local LLM

**Multi-model routing survives:** The 3-tier routing system (Agent Booster → Haiku → Sonnet/Opus) maps to local equivalents:
- Tier 1 (Agent Booster): unchanged — regex transforms, no LLM needed
- Tier 2 (Haiku equivalent): small local model (7B-13B) for simple tasks
- Tier 3 (Sonnet/Opus equivalent): large local model (70B+) for complex reasoning

---

## What Gets Better After Migration

| Aspect | On Claude | On Local LLM |
|--------|-----------|--------------|
| Cost | Per-token pricing (Opus: $15/$75 per 1M tokens) | Fixed hardware cost, zero marginal cost per token |
| Privacy | Conversations sent to Anthropic's servers | All data stays local |
| Latency (embedding) | VoyageAI API round-trip (~200ms) | Local inference (~10-50ms) |
| Latency (generation) | Claude API (~2-5s first token) | Local inference (~0.5-2s first token, depends on hardware) |
| Availability | Depends on Anthropic's uptime | Runs offline, 100% uptime |
| Rate limits | API rate limits, usage caps | None — hardware is the only limit |
| Context freshness | Weekly sync delay | Real-time — conversations persist as they happen |
| Lineage detection | Retroactive (during sync) | Real-time (during conversation) |
| Customization | Prompt engineering only | Fine-tuning on personal conversation history |
| Project sandboxing | Hard barrier (Claude enforces) | No barrier — local LLM sees everything |

The last row is the most important. Claude's project sandboxing is the root cause of the manual merge problem. A local LLM has no sandboxing — it can access the entire vectordb, all projects, all conversations. The cross-project attention mechanism that Forge OS builds with vector search becomes native: the LLM can directly query the decision registry, check for conflicts, and load relevant context from any project without pre/post scripts as intermediaries.

This collapses Layer 1.5 (SYNC) entirely. The three-layer separation (specification/sync/persistence) was a workaround for Claude's runtime isolation. With a local LLM that has direct MongoDB access, the sync layer disappears — the knowledge engine IS the specification layer AND has direct persistence access.

```
On Claude (current):                    On Local LLM (target):
┌──────────────────────┐                ┌──────────────────────┐
│ Specification (Claude)│                │ Knowledge Engine     │
└──────────┬───────────┘                │  (local LLM +        │
           │ user copies text           │   direct DB access)  │
┌──────────┴───────────┐                │                      │
│ Sync (pre/post scripts)│               │  - Generates          │
└──────────┬───────────┘                │  - Compresses         │
           │ function calls             │  - Queries vectordb   │
┌──────────┴───────────┐                │  - Detects conflicts  │
│ Persistence (vectordb)│                │  - Builds lineage     │
└──────────────────────┘                └──────────┬───────────┘
                                                   │ direct access
                                        ┌──────────┴───────────┐
                                        │ Persistence (vectordb)│
                                        └──────────────────────┘
```

---

## What Gets Worse (and Mitigations)

| Aspect | Tradeoff | Mitigation |
|--------|---------|------------|
| Reasoning quality | Local 70B < Claude Opus for complex reasoning | Use largest feasible model; fine-tune on personal conversation patterns; accept that some tasks may need a cloud fallback |
| Code generation quality | Local models produce more errors | Stronger TDD discipline; automated test gates before accepting generated code |
| Hardware cost | GPUs are expensive ($2K-$10K for 2x RTX 4090) | One-time cost vs ongoing API spend. Break-even at ~$200-400/month Claude usage over 6-18 months. |
| Setup complexity | Ollama/vLLM require configuration | Automate via Forge OS init script; Docker container for reproducible setup |
| Model updates | Must manually update local models | Automated model pull via Ollama; version pin in config |
| Structured output reliability | Local models less reliable at following schemas | Constrained decoding (llama.cpp grammar mode); output validation + retry |

### The Cloud Fallback

The knowledge engine interface supports multiple backends simultaneously. During migration, the system can route:
- Simple tasks (classification, embedding, simple generation) → local LLM
- Complex tasks (architecture decisions, security analysis, novel code generation) → Claude API

This hybrid mode allows gradual migration without a hard cutover. The routing is based on task complexity (the same 3-tier system already in place), and the threshold for "needs cloud" shrinks as local models improve.

---

## Fine-Tuning on Personal Data

The most powerful capability unlocked by local LLMs: **fine-tuning on the user's own conversation history.**

The vectordb already contains 3,777 messages across 225 conversations, classified by content type (`code_pattern`, `decision`, `solution`, `error_recovery`, `optimization`, `routing`). This is a ready-made fine-tuning dataset.

**What to fine-tune on:**
1. **Compression protocol execution** — train the model to produce well-structured archives from conversation state, using past compressions as examples
2. **Decision style** — train on past D001-style decisions with rationale to match the user's reasoning patterns
3. **Code patterns** — train on code_pattern classified messages to learn preferred coding style
4. **Epistemic tier calibration** — train on past tier assignments to calibrate the model's confidence scoring to match the user's standards

**What NOT to fine-tune on:**
- Raw conversation text (too noisy, includes pleasantries and tangents)
- Speculative decisions (tier < 0.3) — these are noise by definition
- Abandoned threads — models learn from success, not from dead ends

**Format:** LoRA fine-tuning (Low-Rank Adaptation) on the base model. ~4-8 hours on a single GPU for 3,777 messages. The LoRA adapter is ~100-500MB, stored alongside the base model. Multiple adapters can be loaded for different task types (compression adapter, code adapter, reasoning adapter).

This is the path to a knowledge engine that doesn't just process prompts — it has internalized the user's decision-making patterns, coding style, and domain expertise. The vectordb provides the facts (decisions, threads, lineage). The fine-tuned model provides the reasoning style. Together, they approximate a persistent cognitive partner that improves over time.

---

## Implementation Checklist

- [ ] **Phase 0:** Create `vectordb/engine.py` with `KnowledgeEngine` interface. Refactor all LLM calls to go through it. Ship `ClaudeEngine` as default implementation.
- [ ] **Phase 1:** Evaluate local embedding models (nomic-embed, bge-large). Run parallel comparison on 100 queries. If retrieval overlap > 0.8, implement `LocalEmbedder` in engine interface.
- [ ] **Phase 2:** Build local conversation storage. Chat interface writes turns directly to MongoDB. UUIDv8 assigned at creation. Real-time embedding and lineage detection.
- [ ] **Phase 3:** Evaluate local LLMs for compression protocol execution. Test structured output reliability on 20 sample compressions. Implement `LocalEngine` with constrained decoding.
- [ ] **Phase 4:** Route claude-flow agent execution through knowledge engine interface. Multi-model routing: small local model for Tier 2, large local model for Tier 3.
- [ ] **Phase 5:** Fine-tune LoRA adapters on classified conversation history. Evaluate compression quality, decision style match, and code pattern adherence.
- [ ] **Phase 6:** Remove Claude API dependency entirely. `ClaudeEngine` becomes optional fallback, not default.

---

## The Endgame

When all phases are complete, Forge OS is:

- A **local-first** system — all data, all inference, all coordination happens on the user's hardware
- A **self-improving** system — fine-tuned on its own successful outputs, with the vectordb as the training data source
- A **protocol-driven** system — the compression skill, YAML schemas, epistemic tiers, and UUIDv8 IDs are LLM-agnostic protocols that any model can execute
- A **zero marginal cost** system — no per-token pricing, no API rate limits, no vendor lock-in

The compression skill was designed inside Claude, but it was designed AS A PROTOCOL — not as a Claude feature. The vectordb was built on MongoDB, not on Claude's infrastructure. The UUIDv8 ID system is pure math. The graph structure is pure data. The conflict resolution policy is pure logic. None of these require Claude. They require a reasoning engine. Claude is one. A local 70B model is another. The interface is the same.

The user's conversations with Claude are the training data for the system that replaces Claude. Every `compress --lossless` archive is a labeled example of correct compression. Every decision with an epistemic tier is a calibration point. Every resolved thread is a positive training signal. The 225 conversations and 3,777 messages in the vectordb aren't just history — they're the curriculum for the local model that will run Forge OS autonomously.
