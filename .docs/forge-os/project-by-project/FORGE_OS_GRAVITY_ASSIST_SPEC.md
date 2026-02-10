# Forge OS: Gravity Assist — Dual-Lens Orchestrated Recall

## 1. Context & Motivation

Forge OS currently gives LLMs persistent memory through attention-weighted recall (`vectordb/attention.py`), cross-project entanglement scanning (`vectordb/entanglement.py`), and 15 MCP tools. But every recall query today targets a single project or searches globally with no sense of *why* different projects produce different results.

**The insight:** Michael uses two Claude.ai projects — The Nexus and The Cartographer's Codex — with the *same prompt* but for fundamentally different purposes:

- **The Nexus** (connector lens): Finds cross-domain associations, isomorphisms, unexpected bridges between concepts
- **The Cartographer's Codex** (navigator lens): Evaluates validated decisions, rejected alternatives, strategic direction

Neither project alone is sufficient. The Nexus finds brilliant connections with no direction. The Codex provides validated paths with no lateral insight. Together, they act as a **gravity assist** — bending the LLM's probability field toward decisions that are both creative (Nexus-bent) and grounded (Codex-bent).

**What this plan builds:** An orchestration layer that treats projects as **epistemic lenses** with declared roles, runs parallel recall through each lens, detects convergence and divergence between lenses via entanglement data, and returns a combined gravitational field that reshapes the LLM's reasoning trajectory.

### Decision D024 (tier 0.9)

> "Nexus + Codex dual-lens orchestration acts as a gravity assist for LLM reasoning. The attention score functions as gravitational mass. Entanglement clusters are convergent gravity points where both lenses reinforce. This is trajectory-augmented generation, not just retrieval-augmented generation."

### Related Flag (isomorphism)

> Physics-to-AI isomorphism: gravitational slingshot mechanics map to attention-weighted context injection. Spacecraft = prompt, planets = project knowledge bases, trajectory = token probability distribution, gravitational mass = attention score.

---

## 2. System Architecture

```
                    ┌─────────────────────────┐
                    │     LLM (prompt)         │
                    │    "the spacecraft"      │
                    └───────────┬──────────────┘
                                │
                                ▼
                    ┌─────────────────────────┐
                    │   forge_orchestrate()    │
                    │   vectordb/gravity.py    │
                    └───────────┬──────────────┘
                                │
              ┌─────────────────┼─────────────────┐
              │                 │                  │
              ▼                 ▼                  ▼
    ┌──────────────┐  ┌──────────────┐  ┌──────────────┐
    │  LENS 1      │  │  LENS 2      │  │  LENS N      │
    │  connector   │  │  navigator   │  │  builder     │
    │  (The Nexus) │  │  (Codex)     │  │  (Reality)   │
    │              │  │              │  │              │
    │  recall()    │  │  recall()    │  │  recall()    │
    │  scoped to   │  │  scoped to   │  │  scoped to   │
    │  project     │  │  project     │  │  project     │
    └──────┬───────┘  └──────┬───────┘  └──────┬───────┘
           │                 │                  │
           └────────┬────────┴──────────┬───────┘
                    │                   │
                    ▼                   ▼
           ┌───────────────┐   ┌───────────────┐
           │  CONVERGENCE  │   │  DIVERGENCE   │
           │  Detection    │   │  Detection    │
           │               │   │               │
           │  entanglement │   │  conflict     │
           │  clusters     │   │  detection    │
           │  + semantic   │   │  + missing    │
           │  overlap      │   │  coverage     │
           └───────┬───────┘   └───────┬───────┘
                   │                   │
                   └─────────┬─────────┘
                             │
                             ▼
                   ┌───────────────────┐
                   │  FIELD COMPOSER   │
                   │                   │
                   │  Convergence →    │
                   │    mass amplified │
                   │  Divergence →     │
                   │    tension flagged│
                   │  Budget trim →    │
                   │    context text   │
                   └─────────┬─────────┘
                             │
                             ▼
                   ┌───────────────────┐
                   │  Exit trajectory  │
                   │  (context_text)   │
                   │  injected into    │
                   │  LLM prompt       │
                   └───────────────────┘
```

### Relationship to Existing Layers

| Forge OS Layer | Component | Gravity Assist Integration |
|---|---|---|
| Layer 3: ATTENTION | `attention.py` | `recall()` called per-lens; `compute_attention()` provides gravitational mass |
| Layer 2: GRAPH | `entanglement.py` | Cached scans provide convergence points between lenses |
| Layer 2: GRAPH | `conflicts.py` | Divergence detection reuses conflict signals |
| Layer 2: GRAPH | `decision_registry.py` | Decisions carry epistemic tier → mass in field |
| Layer 2: GRAPH | `thread_registry.py` | Open threads from navigator lens = directional pull |
| Layer 2.5: EXPEDITION | `priming_registry.py` | Territory activation scoped per-lens |
| Layer 1: MEMORY | `patterns.py` | Learned patterns surface in builder lens |
| MCP Server | `mcp_server.py` | New `forge_orchestrate` + `forge_roles` tools |
| HTTP API | `api_server.py` | New `/api/forge/orchestrate` + `/api/forge/roles` endpoints |

### Integration with Spec'd Components (Future)

| Component | Integration Point |
|---|---|
| **The Arbiter** (routing) | Gravity assist output informs model routing — if navigator lens strongly rejects a path, Arbiter deprioritizes models favoring it |
| **The Evaluator** (quality) | Per-lens results get quality-scored; divergence between lenses triggers re-evaluation |
| **The Guardian** (constraints) | Cross-lens constraint conflicts escalate to Guardian veto; epistemic tier violations across lenses flagged |
| **Mission Control** (orchestration) | Multi-lens analysis feeds task decomposition — Nexus suggests exploration, Codex suggests direction, Mission Control sequences |

---

## 3. Existing Code Surface

### Functions reused directly (no modification needed)

| Function | File | Used For |
|---|---|---|
| `recall(query, project, budget)` | `vectordb/attention.py:328` | Per-lens attention-weighted search |
| `compute_attention(...)` | `vectordb/attention.py:56` | Gravitational mass calculation |
| `_parallel_search(...)` | `vectordb/attention.py:205` | Per-lens collection search |
| `_budget_trim(results, budget)` | `vectordb/attention.py:235` | Final output budget constraint |
| `enrich_with_entanglement(results)` | `vectordb/attention.py:285` | Cluster data for convergence detection |
| `get_latest_scan(project)` | `vectordb/entanglement.py:710` | Cached entanglement clusters |
| `embed_query(text)` | `vectordb/embeddings.py:35` | Query embedding (shared across lenses) |
| `get_active_decisions(project)` | `vectordb/decision_registry.py` | Navigator lens: validated decisions |
| `get_active_threads(project)` | `vectordb/thread_registry.py` | Navigator lens: open questions |
| `find_relevant_priming(topic, project)` | `vectordb/priming_registry.py:163` | Per-lens territory activation |
| `detect_conflicts(text, tier, project)` | `vectordb/conflicts.py:28` | Divergence detection signal |
| `list_projects(db)` | `vectordb/conversation_registry.py` | Available projects and their UUIDs |
| `get_database()` | `vectordb/db.py` | MongoDB connection |
| `emit_event(type, details)` | `vectordb/events.py` | Audit trail |
| `_serialize(obj)` | `scripts/mcp_server.py:43` | Response serialization |

### Reference patterns

- `attention.py:recall()` — The orchestrate function follows the same embed-once → parallel-search → score → enrich → budget-trim pipeline, but runs it N times (once per lens) and adds convergence/divergence on top.
- `entanglement.py:_cluster_resonances()` — Union-Find clustering pattern reused for grouping convergent results across lenses.
- `config.py` — All new thresholds defined as module-level constants.
- `mcp_server.py` — All tools follow the try/except → `_json_response()` pattern.

---

## 4. Data Models

### Project Roles (new MongoDB collection: `project_roles`)

```python
{
    "project_name": str,          # "The Nexus"
    "project_uuid": str,          # from conversation_registry
    "role": str,                  # "connector" | "navigator" | "builder" | "evaluator" | "critic" | "compiler"
    "gravity_type": str,          # "lateral" | "directional" | "implementation" | "quality" | "critical" | "synthesis"
    "description": str,           # "Cross-domain associations, isomorphisms, bridges"
    "weight": float,              # 0.0-1.0, default 1.0 — role weight in field composition
    "active": bool,               # Whether this role assignment is active
    "created_at": str,            # ISO 8601
    "updated_at": str,            # ISO 8601
}
```

### Lens Configuration (new MongoDB collection: `lens_configurations`)

A lens is a named, reusable set of project roles for orchestrated analysis.

```python
{
    "lens_name": str,             # "gravity-assist" | "full-spectrum" | "build-review"
    "description": str,           # "Nexus (connector) + Codex (navigator) dual-field analysis"
    "projects": [                 # Ordered list of project-role assignments
        {
            "project_name": str,  # "The Nexus"
            "role": str,          # "connector"
            "weight": float,      # Override weight for this lens (optional)
        }
    ],
    "default_budget": int,        # Default chars for orchestrated output (default 6000)
    "active": bool,
    "created_at": str,
    "updated_at": str,
}
```

### Orchestration Result Shape

```python
{
    "query": str,
    "lens_name": str | None,         # Named lens, or None if ad-hoc
    "lenses_used": [str],             # Role names used

    "per_lens": {                     # Keyed by role name
        "connector": {
            "project": "The Nexus",
            "role": "connector",
            "gravity_type": "lateral",
            "results": [...],         # Attention-scored results
            "result_count": int,
            "top_attention": float,   # Highest attention score in this lens
        },
        "navigator": {
            "project": "The Cartographer's Codex",
            "role": "navigator",
            "gravity_type": "directional",
            "results": [...],
            "result_count": int,
            "top_attention": float,
        },
    },

    "convergence": [                  # Where lenses agree — amplified gravity
        {
            "type": "entanglement_cluster" | "semantic_overlap",
            "lenses": ["connector", "navigator"],
            "items": [...],           # Converging items from each lens
            "cluster_id": int | None, # If from entanglement scan
            "combined_mass": float,   # Amplified attention (sum * convergence_boost)
            "summary": str,           # Brief description
        }
    ],

    "divergence": [                   # Where lenses disagree — decision tension
        {
            "type": "conflicting_direction" | "gap" | "tier_mismatch",
            "lens_a": {"role": str, "item": dict},
            "lens_b": {"role": str, "item": dict},
            "tension_score": float,   # 0-1, how strongly they disagree
            "description": str,
        }
    ],

    "field_summary": {
        "total_candidates": int,
        "convergence_points": int,
        "divergence_points": int,
        "dominant_lens": str,         # Which lens has highest aggregate mass
        "field_coherence": float,     # 0-1, how aligned the lenses are
    },

    "context_text": str,              # Budget-trimmed text for LLM injection
    "budget_used": int,
}
```

### Predefined Role Types

| Role | Gravity Type | Description | Primary Signal |
|---|---|---|---|
| `connector` | lateral | Cross-domain bridges, isomorphisms, associations | Entanglement clusters, cross-project resonances |
| `navigator` | directional | Validated decisions, rejected alternatives, strategic direction | High-tier decisions, resolved threads, lineage chains |
| `builder` | implementation | Technical patterns, architecture decisions, code approaches | Patterns, priming blocks, implementation decisions |
| `evaluator` | quality | Quality scores, success/failure patterns, what worked | Pattern success_scores, resolved threads with outcomes |
| `critic` | critical | Risks, conflicts, stale items, blind spots | Conflicts, stale decisions, pending flags, loose ends |
| `compiler` | synthesis | Compiled expedition findings, priming blocks | Priming registry, compiled flags |

---

## 5. Files to Create

### 5a. `vectordb/gravity.py` (~350 lines)

The gravity assist orchestration engine. Core of the new capability.

```python
"""Forge OS Layer 3.5: GRAVITY — Multi-lens orchestrated recall.

Extends the attention engine with project role awareness and
convergence/divergence detection. Treats each project as an
epistemic lens that bends the LLM's probability field.

No MCP dependency. Called by MCP server and HTTP endpoints.
"""

def orchestrate(
    query: str,
    lenses: list[dict] | None = None,
    lens_name: str | None = None,
    budget: int | None = None,
    min_score: float | None = None,
    db=None,
) -> dict:
    """Multi-lens attention-weighted recall with convergence detection.

    Pipeline:
      1. Resolve lenses (from lens_name config, explicit list, or defaults)
      2. Embed query once (shared across all lenses)
      3. Run recall() in parallel, scoped to each lens's project
      4. Detect convergence via entanglement clusters + semantic overlap
      5. Detect divergence via conflict signals + gap analysis
      6. Compose gravitational field (amplify convergence, flag divergence)
      7. Budget-trim the combined, role-annotated result set

    Args:
        query: Search query text.
        lenses: Explicit list of {project_name, role, weight?} dicts.
        lens_name: Named lens configuration to load from DB.
        budget: Max chars for context_text (default 6000).
        min_score: Minimum attention threshold.
        db: Optional database instance.

    Returns:
        Orchestration result dict (see data model spec).
    """


def _resolve_lenses(lenses, lens_name, db) -> list[dict]:
    """Resolve lens configuration from explicit list, named config, or defaults.

    Priority:
      1. Explicit lenses parameter (ad-hoc orchestration)
      2. Named lens configuration from lens_configurations collection
      3. Default: all projects with assigned roles
    """


def _parallel_lens_recall(query, query_embedding, lenses, min_score, db) -> dict:
    """Run recall() in parallel for each lens, scoped to its project.

    Uses ThreadPoolExecutor with max_workers = len(lenses).
    Each recall call gets the pre-computed query_embedding to avoid
    redundant VoyageAI API calls.

    Returns dict keyed by role name: {role: recall_result}
    """


def _detect_convergence(per_lens_results, db) -> list[dict]:
    """Find where multiple lenses agree — convergent gravity.

    Two detection methods:
      1. Entanglement clusters: Items from different lenses that appear
         in the same cluster (from cached scan) are convergent.
      2. Semantic overlap: Items from different lenses with >0.7 cosine
         similarity to each other indicate thematic agreement.

    Convergent items get a mass amplification bonus.
    """


def _detect_divergence(per_lens_results, db) -> list[dict]:
    """Find where lenses disagree — decision tension.

    Three detection methods:
      1. Conflicting direction: Decision in lens A contradicts decision
         in lens B (reuses conflict detection signals).
      2. Gap: One lens has strong results, another has none — blind spot.
      3. Tier mismatch: Same topic, different epistemic tiers across lenses.

    Divergent items get flagged with tension_score.
    """


def _compose_field(per_lens, convergence, divergence, budget) -> dict:
    """Compose the combined gravitational field.

    Convergent items: mass *= CONVERGENCE_BOOST (1.3)
    Divergent items: flagged but not suppressed
    Budget allocation: convergence points first, then by attention score

    Returns field_summary + budget-trimmed context_text.
    """


def _compute_field_coherence(per_lens, convergence, divergence) -> float:
    """How aligned are the lenses? 1.0 = perfect agreement, 0.0 = full contradiction.

    Formula:
      coherence = (convergence_mass / total_mass)
                - (divergence_tension / total_tension)
                + baseline (0.5)
    Clamped to [0.0, 1.0].
    """
```

### 5b. `vectordb/project_roles.py` (~120 lines)

CRUD for project role assignments and lens configurations.

```python
"""Forge OS Layer 3.5: GRAVITY — Project role assignments and lens configurations.

Manages the mapping between projects and their epistemic roles
in the gravity assist system.
"""

# Role types and their metadata
ROLE_TYPES = {
    "connector":  {"gravity_type": "lateral",        "description": "Cross-domain bridges, isomorphisms, associations"},
    "navigator":  {"gravity_type": "directional",    "description": "Validated decisions, rejected alternatives, strategic direction"},
    "builder":    {"gravity_type": "implementation",  "description": "Technical patterns, architecture decisions, code approaches"},
    "evaluator":  {"gravity_type": "quality",         "description": "Quality scores, success/failure patterns"},
    "critic":     {"gravity_type": "critical",        "description": "Risks, conflicts, stale items, blind spots"},
    "compiler":   {"gravity_type": "synthesis",       "description": "Compiled expedition findings, priming blocks"},
}


def assign_role(project_name, role, weight=1.0, description=None, db=None) -> dict:
    """Assign an epistemic role to a project.

    Validates project exists in conversation_registry.
    Validates role is a known type.
    Upserts (one project can have only one role).
    """


def get_role(project_name, db=None) -> dict | None:
    """Get the role assignment for a project."""


def list_roles(active_only=True, db=None) -> list[dict]:
    """List all project role assignments."""


def remove_role(project_name, db=None) -> dict:
    """Remove a project's role assignment."""


def save_lens(lens_name, projects, description=None, default_budget=6000, db=None) -> dict:
    """Save a named lens configuration.

    Args:
        lens_name: Unique name for this lens combo.
        projects: List of {project_name, role, weight?} dicts.
        description: Human-readable description.
        default_budget: Default budget in chars.
    """


def get_lens(lens_name, db=None) -> dict | None:
    """Get a named lens configuration."""


def list_lenses(db=None) -> list[dict]:
    """List all saved lens configurations."""


def delete_lens(lens_name, db=None) -> dict:
    """Delete a named lens configuration."""
```

---

## 6. Files to Modify

### 6a. `vectordb/config.py` (+20 lines)

```python
# Gravity assist configuration
COLLECTION_PROJECT_ROLES = "project_roles"
COLLECTION_LENS_CONFIGURATIONS = "lens_configurations"

GRAVITY_DEFAULT_BUDGET = 6000           # chars — higher than single recall (4000)
GRAVITY_CONVERGENCE_BOOST = 1.3         # Mass multiplier for convergent items
GRAVITY_CONVERGENCE_THRESHOLD = 0.70    # Cosine similarity for semantic overlap detection
GRAVITY_DIVERGENCE_TIER_DELTA = 0.25    # Min tier difference to flag divergence
GRAVITY_MAX_LENSES = 6                  # Max simultaneous lenses
GRAVITY_BASELINE_COHERENCE = 0.5        # Baseline field coherence
```

### 6b. `vectordb/__init__.py` (+15 lines)

```python
from vectordb.gravity import orchestrate as gravity_orchestrate
from vectordb.project_roles import (
    assign_role,
    get_role,
    list_roles,
    remove_role,
    save_lens,
    get_lens,
    list_lenses,
    delete_lens,
    ROLE_TYPES,
)
```

Add to `__all__`.

### 6c. `scripts/mcp_server.py` (+80 lines)

Two new tools:

```python
@mcp.tool()
def forge_orchestrate(
    query: str,
    lens_name: Optional[str] = None,
    lenses: Optional[str] = None,  # JSON string of [{project_name, role, weight?}]
    budget: Optional[int] = None,
) -> str:
    """Multi-lens gravity assist: orchestrated recall through epistemic lenses.

    Runs parallel attention-weighted recall through multiple projects, each
    acting as a gravitational field. Detects convergence (where lenses agree,
    amplifying mass) and divergence (where they disagree, flagging tension).

    Use named lenses (e.g., "gravity-assist") or specify ad-hoc project-role pairs.

    Args:
        query: What to analyze through multiple lenses.
        lens_name: Named lens configuration (e.g., "gravity-assist").
        lenses: JSON string of ad-hoc lenses: [{"project_name": "The Nexus", "role": "connector"}]
        budget: Max chars for combined context (default 6000).
    """


@mcp.tool()
def forge_roles(
    action: str,
    project: Optional[str] = None,
    role: Optional[str] = None,
    weight: Optional[float] = None,
) -> str:
    """Manage project epistemic roles for gravity assist orchestration.

    Args:
        action: "list", "assign", "remove", or "types".
        project: Project name (required for assign/remove).
        role: Role type (required for assign). Options: connector, navigator,
            builder, evaluator, critic, compiler.
        weight: Role weight 0.0-1.0 (optional, default 1.0).
    """
```

### 6d. `scripts/api_server.py` (+100 lines)

Three new endpoints:

```python
# POST /api/forge/orchestrate
class ForgeOrchestrateBody(BaseModel):
    query: str
    lens_name: str | None = None
    lenses: list[dict] | None = None
    budget: int | None = None

# GET /api/forge/roles
# Returns all project role assignments

# POST /api/forge/roles
class ForgeRoleBody(BaseModel):
    project: str
    role: str
    weight: float = 1.0

# GET /api/forge/lenses
# Returns all saved lens configurations

# POST /api/forge/lenses
class ForgeLensBody(BaseModel):
    lens_name: str
    projects: list[dict]
    description: str | None = None
    default_budget: int = 6000
```

### 6e. `scripts/export_tool_schemas.py` (+30 lines)

Add `forge_orchestrate` and `forge_roles` to the TOOLS list, regenerate all three config files.

---

## 7. Implementation Phases

### Phase 1: Config + Project Roles (~120 lines)

1. Add gravity constants to `vectordb/config.py`
2. Create `vectordb/project_roles.py`:
   - `ROLE_TYPES` dict with metadata
   - `assign_role()` — upsert to `project_roles` collection
   - `get_role()`, `list_roles()`, `remove_role()` — CRUD
   - `save_lens()`, `get_lens()`, `list_lenses()`, `delete_lens()` — lens config CRUD
3. Update `vectordb/__init__.py`
4. **Seed initial roles:**
   - The Nexus → connector
   - The Cartographer's Codex → navigator
   - The Reality Compiler → builder
5. **Seed initial lens:**
   - "gravity-assist" → [{Nexus, connector}, {Codex, navigator}]

**Depends on:** Nothing. All existing functions available.

### Phase 2: Gravity Engine (~350 lines)

1. Create `vectordb/gravity.py`:
   - `_resolve_lenses()` — load from named config, explicit list, or defaults
   - `_parallel_lens_recall()` — ThreadPoolExecutor running `recall()` per-project with shared embedding
   - `_detect_convergence()` — entanglement cluster matching + semantic overlap
   - `_detect_divergence()` — conflict signals + gap analysis + tier mismatch
   - `_compose_field()` — convergence amplification, budget allocation, context text
   - `_compute_field_coherence()` — alignment metric
   - `orchestrate()` — main pipeline orchestrator
2. Update `vectordb/__init__.py`

**Depends on:** Phase 1 (needs role resolution).

**Key implementation detail:** The `recall()` function in `attention.py` calls `embed_query()` internally. To avoid redundant VoyageAI API calls (one per lens), the gravity engine will call `embed_query()` once and pass the embedding to a modified internal path, or call `_parallel_search()` directly with the pre-computed embedding. The cleanest approach is to add an optional `query_embedding` parameter to `recall()` — if provided, skip the embed step.

### Phase 3: Attention Engine Extension (+10 lines)

1. Add optional `query_embedding` parameter to `recall()` in `vectordb/attention.py`:
   ```python
   def recall(query, project=None, budget=None, min_score=None,
              collections=None, query_embedding=None, db=None):
       if query_embedding is None:
           query_embedding = embed_query(query)
       # ... rest unchanged
   ```

This allows the gravity engine to embed once and pass the vector to N `recall()` calls without N VoyageAI API calls.

**Depends on:** Nothing. Backward-compatible change.

### Phase 4: MCP + HTTP + Schema Export (+210 lines)

1. Add `forge_orchestrate` tool to `scripts/mcp_server.py`
2. Add `forge_roles` tool to `scripts/mcp_server.py`
3. Add endpoints to `scripts/api_server.py`:
   - `POST /api/forge/orchestrate`
   - `GET /api/forge/roles`
   - `POST /api/forge/roles`
   - `GET /api/forge/lenses`
   - `POST /api/forge/lenses`
4. Add tool definitions to `scripts/export_tool_schemas.py`
5. Run `python scripts/export_tool_schemas.py` to regenerate config files

**Depends on:** Phases 1-3.

### Phase 5: Integration & Verification

1. Seed roles and lens config
2. Run verification tests (see section 9)
3. Test via MCP (Claude Code) and HTTP (curl)

**Depends on:** All previous phases.

```
Phase 1 (roles) ──┐
                   ├── Phase 2 (gravity engine)
Phase 3 (recall    │        │
 extension) ───────┘        │
                             ├── Phase 4 (MCP + HTTP + schemas)
                             │
                             └── Phase 5 (integration)
```

**Phases 1 and 3 can run in parallel** — they're independent. Phase 2 depends on both. Phase 4 depends on Phase 2. Phase 5 depends on Phase 4.

---

## 8. Key Patterns & Constraints

### Gravitational Mass = Attention Score

The attention formula already computes a multi-signal score:
```
attention = similarity * 0.45 + epistemic_tier * 0.20 + freshness * 0.15
          + conflict_salience * 0.10 + category_boost * 0.10
```

This score *is* the gravitational mass. No new scoring formula needed — the gravity assist operates on top of attention scores, not replacing them.

### Convergence Amplification

When items from different lenses fall in the same entanglement cluster (or have >0.70 cosine similarity to each other), their mass is amplified:

```python
amplified_mass = original_attention * GRAVITY_CONVERGENCE_BOOST  # 1.3
```

This means convergent items float to the top of the budget-trimmed output.

### Divergence Flagging (Not Suppression)

Divergent results are flagged but never suppressed. Tension between lenses is information, not error. The divergence list lets the LLM reason about *why* lenses disagree.

### Single Embedding, N Lenses

A query is embedded once via VoyageAI. The same 1024-dim vector is passed to each lens's `recall()` call. This means N lenses cost 1 embedding API call, not N.

### Budget Allocation

The combined budget (default 6000 chars) is divided:
1. **Convergence points first** — convergent items get priority (highest combined mass)
2. **Per-lens results** — remaining budget split proportionally by lens weight
3. **Divergence annotations** — appended as structured notes, not counted against main budget

### Anti-Patterns to Avoid

- **Do not merge results across lenses before scoring.** Each lens must maintain its identity so the LLM knows which gravitational field produced which result.
- **Do not suppress low-scoring lenses.** A lens with few results is still informative (gap = potential blind spot).
- **Do not hardcode project-to-role mappings.** Roles are data, not code. Stored in MongoDB, editable at runtime.
- **Do not create a new collection for orchestration results.** Results are ephemeral (per-query), not persisted. Only roles and lens configs are persisted.

### Immutability

All functions return new dicts — no mutation of input data. Per coding style rules.

---

## 9. Verification Checklist

### Phase 1: Roles & Lens Config

```bash
# Assign roles
python3 -c "
from vectordb.project_roles import assign_role, list_roles
assign_role('The Nexus', 'connector')
assign_role(\"The Cartographer's Codex\", 'navigator')
assign_role('The Reality Compiler', 'builder')
for r in list_roles():
    print(f\"{r['project_name']}: {r['role']} ({r['gravity_type']})\")
"

# Save lens config
python3 -c "
from vectordb.project_roles import save_lens, get_lens
save_lens('gravity-assist', [
    {'project_name': 'The Nexus', 'role': 'connector'},
    {'project_name': \"The Cartographer's Codex\", 'role': 'navigator'},
], description='Nexus (connector) + Codex (navigator) dual-field analysis')
print(get_lens('gravity-assist'))
"
```

### Phase 2: Gravity Engine

```bash
# Basic orchestration
python3 -c "
from vectordb.gravity import orchestrate
result = orchestrate('How should we handle authentication for enterprise?',
                     lens_name='gravity-assist')
print(f'Lenses: {result[\"lenses_used\"]}')
print(f'Convergence points: {result[\"field_summary\"][\"convergence_points\"]}')
print(f'Divergence points: {result[\"field_summary\"][\"divergence_points\"]}')
print(f'Field coherence: {result[\"field_summary\"][\"field_coherence\"]:.2f}')
print(f'Budget used: {result[\"budget_used\"]}')
for role, data in result['per_lens'].items():
    print(f'  [{role}] {data[\"project\"]}: {data[\"result_count\"]} results, '
          f'top_attention={data[\"top_attention\"]:.3f}')
"

# Ad-hoc 3-lens orchestration
python3 -c "
from vectordb.gravity import orchestrate
result = orchestrate('knowledge preservation patterns', lenses=[
    {'project_name': 'The Nexus', 'role': 'connector'},
    {'project_name': \"The Cartographer's Codex\", 'role': 'navigator'},
    {'project_name': 'The Reality Compiler', 'role': 'builder'},
])
print(f'Lenses: {len(result[\"lenses_used\"])}')
print(f'Coherence: {result[\"field_summary\"][\"field_coherence\"]:.2f}')
print(result['context_text'][:500])
"
```

### Phase 3: Recall Extension

```bash
# Verify backward compatibility
python3 -c "
from vectordb.attention import recall
result = recall('authentication patterns')  # No query_embedding — should work as before
print(f'Results: {len(result[\"results\"])}')
"
```

### Phase 4: MCP + HTTP

```bash
# MCP tool listing
echo '{}' | python3 -c "
import json, sys
sys.path.insert(0, '.')
# Verify forge_orchestrate and forge_roles are in the tool list
from scripts.export_tool_schemas import TOOLS
names = [t['name'] for t in TOOLS]
assert 'forge_orchestrate' in names, 'Missing forge_orchestrate'
assert 'forge_roles' in names, 'Missing forge_roles'
print(f'Tools: {len(TOOLS)} (includes forge_orchestrate, forge_roles)')
"

# HTTP endpoints
curl -X POST http://localhost:8000/api/forge/orchestrate \
  -H 'Content-Type: application/json' \
  -d '{"query": "decision lineage patterns", "lens_name": "gravity-assist"}'

curl http://localhost:8000/api/forge/roles

curl -X POST http://localhost:8000/api/forge/roles \
  -H 'Content-Type: application/json' \
  -d '{"project": "Wavelength", "role": "evaluator"}'

curl http://localhost:8000/api/forge/lenses

# Schema export
python3 scripts/export_tool_schemas.py
python3 -c "
import json
tools = json.load(open('config/forge_tools_anthropic.json'))
names = [t['name'] for t in tools]
print(f'Exported {len(tools)} tools')
assert 'forge_orchestrate' in names
assert 'forge_roles' in names
"
```

### End-to-End: Claude Code

```
# In Claude Code (after MCP registration):
> forge_orchestrate("How should enterprise knowledge preservation work?",
                    lens_name="gravity-assist")
# Should return: connector (Nexus) results showing cross-domain bridges
#                navigator (Codex) results showing validated decisions
#                convergence points where both agree
#                divergence points where they disagree
```

---

## 10. Dependencies

- No new packages required. All functionality built on existing `vectordb/` modules.
- `mcp>=1.0.0` already required for the MCP server (from Phase 2 of the original plan).
- VoyageAI API calls: 1 per orchestration query (embedding shared across lenses).

---

## 11. File Size Estimates

| File | Lines | Action |
|---|---|---|
| `vectordb/gravity.py` | ~350 | Create |
| `vectordb/project_roles.py` | ~120 | Create |
| `vectordb/config.py` | +20 | Modify |
| `vectordb/__init__.py` | +15 | Modify |
| `vectordb/attention.py` | +5 | Modify (add `query_embedding` param) |
| `scripts/mcp_server.py` | +80 | Modify |
| `scripts/api_server.py` | +100 | Modify |
| `scripts/export_tool_schemas.py` | +30 | Modify |
| **Total** | **~720** | |

---

## 12. Phase Execution Order

```
Phase 1 (roles, ~120 lines) ──────┐
                                    ├── Phase 2 (gravity engine, ~350 lines)
Phase 3 (recall extension, ~5 lines)─┘        │
                                                │
                                                ├── Phase 4 (MCP + HTTP + schemas, ~210 lines)
                                                │
                                                └── Phase 5 (integration + verification)
```

**Critical path:** Phase 1 + Phase 3 → Phase 2 → Phase 4 → Phase 5

**Parallelizable:** Phases 1 and 3 are independent. Within Phase 4, MCP, HTTP, and schema export are independent.

**Estimated total:** ~720 new/modified lines across 8 files.

---

## Appendix A: Example Orchestrated Output

```
Query: "How should we handle authentication for the enterprise API?"
Lens: gravity-assist (connector + navigator)

=== CONNECTOR (The Nexus) — lateral gravity ===
[decision|0.84] D015 (The Nexus): Authentication patterns share deep isomorphism
  with trust networks in social systems — verify-then-delegate pattern appears in
  OAuth, diplomatic credentials, and cellular immunity.
[thread|0.71] T004 (The Nexus): Can immune system "self/non-self" distinction
  inform zero-trust architecture?

=== NAVIGATOR (The Cartographer's Codex) — directional gravity ===
[decision|0.79] D022 (Codex): Use OAuth2 + RBAC for enterprise tier. Tier 0.85.
  Rationale: JWT-only rejected — doesn't support token revocation at scale.
[decision|0.68] D019 (Codex): Session management must survive across compression
  hops. Scratchpad TTL insufficient for enterprise sessions.

=== CONVERGENCE (amplified gravity) ===
[cluster #7] Both lenses reference "trust delegation" — Nexus from cross-domain
  pattern matching (immune systems), Codex from concrete architecture decision
  (OAuth2 delegation). Combined mass: 1.06 (amplified from 0.84 + 0.79)

=== DIVERGENCE (decision tension) ===
[gap] Navigator has strong auth direction (D022, D019) but Connector has no
  implementation-level patterns. Consider adding Builder lens (The Reality
  Compiler) for technical implementation context.

=== FIELD SUMMARY ===
Coherence: 0.72 | Dominant lens: navigator | Convergence: 1 | Divergence: 1
```

## Appendix B: Future Extensions

### Multi-Model Gravity Assist

When The Arbiter routes tasks to different models, each model could be treated as a lens. Claude's output through The Nexus vs. Gemini's output through The Codex would produce different gravitational fields — the orchestrator combines them.

### Temporal Lenses

Run the same query through a project's knowledge *at different points in time* — "how did our auth thinking evolve?" This leverages the lineage system to reconstruct past knowledge states.

### Adaptive Lens Weighting

Track which lens configurations produce the best outcomes (via pattern_store feedback). Over time, automatically adjust lens weights based on success history.

### Guardian Integration

The Guardian could enforce constraints across lens outputs:
- If connector lens suggests an approach the navigator lens has explicitly rejected (D022: "JWT-only rejected"), Guardian blocks the suggestion
- If epistemic tiers conflict across lenses (tier 0.9 in one, tier 0.3 in another), Guardian escalates

### Enterprise Multi-Tenant Lenses

In the enterprise context (knowledge rot prevention), different departments become lenses:
- Engineering → builder lens
- Compliance → critic lens
- Strategy → navigator lens
- R&D → connector lens

Same orchestration engine, different organizational semantics.
