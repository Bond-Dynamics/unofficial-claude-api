# Lossy Compression Schema

## YAML Template

```yaml
compression_mode: lossy

conversation_state:
  session_id: [unique identifier]
  turns_compressed: [count]
  compression_timestamp: [ISO 8601]
  last_compressed_tag: [CONCEPT_DETAIL_RESULT]
  last_compressed_turn_count: [turn number]

  # --- PARTIAL COMPRESSION (omit entirely for full compression) ---
  compression_scope:
    mode: full | partial
    turn_range: [start, end]         # e.g. [21, 35] — which turns are being compressed
    scope_topic: [natural language]   # optional topic filter applied within turn range
    prior_compression_tag: [tag]     # tag of the compression this builds on (if any)
    context_query: [keywords or tag] # what the user provided via --context flag or natural language

  inherited_context:
    source: [exact tag | keyword match | hybrid]
    source_description: [1-2 sentences: what the inherited context represents]
    carried_decisions:
      - id: [original decision ID from prior compression or conversation]
        tier: [0.0 - 1.0]
        decision: [what was decided]
        relevance: [why this decision matters to the current scope]
    carried_constraints:
      - [constraint that carries forward into current scope]
    carried_frameworks:
      - name: [framework or model name]
        summary: [1-2 sentence description]
        relevance: [how it informs current scope]
  # --- END PARTIAL COMPRESSION ---

  problem_definition:
    original_intent: [1-2 sentences: what user actually wanted]
    refined_intent: [how understanding evolved, if changed]
    domain: [primary subject area]

  decisions_made:
    - id: D001
      tier: [0.0 - 1.0]  # epistemic confidence
      decision: [what was decided]
      rationale: [why, 1-2 sentences max]
      alternatives_rejected: [list if relevant]
      turn_reference: [when decided]

  constraints_discovered:
    explicit:
      - [constraints stated by user]
    implicit:
      - [constraints inferred through iteration]

  artifacts_produced:
    - id: A001
      type: [code | schema | prompt | analysis | document]
      name: [artifact name]
      summary: [what it does, NOT full content]
      status: [draft | final | needs-iteration]
      version: [if multiple iterations]

  iteration_history:
    - issue: [what was wrong]
      resolution: [how fixed]
      artifacts_affected: [A001, A002]

  open_threads:
    - id: T001
      description: [unresolved question or next step]
      priority: [high | medium | low]
      blocked_by: [dependencies if any]

  continuation_prompt: |
    [Self-contained paragraph for new instance.
    Must be readable with zero prior context.
    For partial compressions: foundational context section first,
    then current session decisions, then open threads.]
```

## Output Format

```markdown
## COMPRESSION

**Session:** [identifier]
**Turns Compressed:** [count]
**Scope:** [full | partial (turns N-M, bridging from TAG/KEYWORDS)]

**Conversation State:**
```yaml
[Full YAML per schema above]
```

**Continuation Prompt (copy to new session):**

---
[Self-contained context block including:
- Role/expertise needed
- Foundational context (for partial: inherited decisions/frameworks)
- Problem state
- Decisions already made (don't re-derive)
- Current artifact state
- Explicit next action requested]
---
```

## Example: Full Compression

```yaml
conversation_state:
  session_id: api-design-2024-01
  turns_compressed: 8
  last_compressed_tag: TENANT_PATH_URL_DECISION
  last_compressed_turn_count: 8

  problem_definition:
    original_intent: Design REST API for user management system
    refined_intent: Design REST API with RBAC, supporting multi-tenant architecture

  decisions_made:
    - id: D001
      tier: 0.85
      decision: Use UUID v7 for all resource IDs
      rationale: Sortable, no coordination required, K-sortable for DB performance
      alternatives_rejected: [auto-increment, UUID v4]

    - id: D002
      tier: 0.7
      decision: Nest tenant context in URL path, not header
      rationale: Cacheable, explicit, debuggable in logs
      alternatives_rejected: [X-Tenant-ID header]

  constraints_discovered:
    explicit: [Must support 10K tenants, 100K users per tenant]
    implicit: [Team unfamiliar with GraphQL, existing auth uses JWT]

  artifacts_produced:
    - id: A001
      type: schema
      name: OpenAPI User CRUD
      summary: User CRUD endpoints with RBAC annotations
      status: draft - needs pagination design

  open_threads:
    - id: T001
      description: Pagination strategy (cursor vs offset)
      priority: high
    - id: T002
      description: Bulk operations endpoint design
      priority: medium
```

**Example Continuation Prompt (Full):**

---
You are continuing an API design session for a multi-tenant user management REST API.

**Decisions already made (do not revisit):**
- UUID v7 for resource IDs (sortable, no coordination)
- Tenant context in URL path: `/t/{tenant}/users` (not header)
- REST over GraphQL (team familiarity)
- JWT-based auth (existing infrastructure)

**Current artifact:** Draft OpenAPI schema for User CRUD with RBAC. Endpoints defined, pagination not yet designed.

**Constraints:** 10K tenants, 100K users/tenant scale. Team prefers explicit over magic.

**Open threads requiring resolution:**
1. Pagination: cursor-based vs offset (cursor preferred for scale, need to confirm)
2. Bulk operations: separate endpoints vs batch request body
3. Rate limiting: per-tenant quotas, implementation approach

**Next action:** Finalize pagination strategy and update OpenAPI schema.
---

## Example: Partial Compression

```yaml
conversation_state:
  session_id: consciousness-math-codebreaker-01
  turns_compressed: 15
  compression_timestamp: 2026-02-08T14:30:00Z
  last_compressed_tag: MATH_CURRICULUM_CODEBREAKER_BRIDGE
  last_compressed_turn_count: 35

  compression_scope:
    mode: partial
    turn_range: [21, 35]
    scope_topic: "remedial math program and Operation Codebreaker integration"
    prior_compression_tag: ATTENTION_CONSCIOUSNESS_FRAMEWORK
    context_query: "attention consciousness framework"

  inherited_context:
    source: exact tag
    source_description: "Theoretical framework positing attention as a fundamental field operating on probability space, analogous to gravity on spacetime. Formalizing this requires advanced mathematics."
    carried_decisions:
      - id: D003
        tier: 0.4
        decision: "Attention operates as a fundamental field on probability space"
        relevance: "Foundational theory the math curriculum is designed to eventually formalize"
      - id: D005
        tier: 0.6
        decision: "Formalization requires competency in topology, information theory, differential geometry, and measure theory"
        relevance: "Defines the advanced-level curriculum targets the remedial program must build toward"
    carried_constraints:
      - "Mathematical pedagogy must bridge from remedial foundations to research-level abstractions"
    carried_frameworks:
      - name: Consciousness-Physics Model
        summary: "Attention as a field on probability space; consciousness as the metric tensor of subjective experience"
        relevance: "End-goal application that motivates the entire math curriculum design"

  problem_definition:
    original_intent: Build a remedial-to-advanced math curriculum for personal use
    refined_intent: Expand the math curriculum into Operation Codebreaker's apprenticeship program for veterans
    domain: Educational curriculum design / mathematics pedagogy

  decisions_made:
    - id: D010
      tier: 0.7
      decision: Structure curriculum as a progressive skill tree from algebra through topology
      rationale: Mirrors game-theory pedagogy already designed for Codebreaker; enables mastery gating
      alternatives_rejected: [linear textbook sequence, topic-based modules]

    - id: D011
      tier: 0.8
      decision: Dual-track curriculum — practical software math AND theoretical foundations
      rationale: Veterans need immediately applicable skills (statistics, linear algebra for ML) alongside the theoretical track toward consciousness-physics formalization
      alternatives_rejected: [single theoretical track]

    - id: D012
      tier: 0.6
      decision: Integrate math program into Operation Codebreaker as a core module
      rationale: Math literacy is a force multiplier for software engineering apprenticeship; fills a gap in existing curriculum
      alternatives_rejected: [keep as separate personal project]

  constraints_discovered:
    explicit:
      - No assumed math prerequisites beyond basic arithmetic
      - Must serve veterans with varying educational backgrounds
    implicit:
      - Practical motivation must precede abstract theory (audience-driven)
      - Must integrate with Codebreaker's existing game-theory-based pedagogy framework

  artifacts_produced:
    - id: A003
      type: document
      name: Math Curriculum Skill Tree
      summary: Progressive curriculum map from remedial algebra through advanced topics, with dual practical/theoretical tracks
      status: draft
      version: 1

  open_threads:
    - id: T005
      description: Map which math topics serve BOTH consciousness-physics formalization AND practical software engineering
      priority: high
    - id: T006
      description: Design mastery assessment gates between curriculum levels
      priority: medium
    - id: T007
      description: Integrate with Codebreaker's existing game-theory pedagogy and incentive structures
      priority: medium
      blocked_by: [T005]

  continuation_prompt: |
    See below.
```

**Example Continuation Prompt (Partial):**

---
You are continuing a conversation about a remedial-to-advanced math curriculum being integrated into Operation Codebreaker, a software development apprenticeship program for military veterans.

**Foundational context (from prior session ATTENTION_CONSCIOUSNESS_FRAMEWORK):**
- A theoretical framework posits attention as a fundamental field operating on probability space, analogous to gravity on spacetime
- Formalizing this theory requires competency in topology, information theory, differential geometry, and measure theory
- This framework motivated building a structured math program to develop the mathematical fluency needed for formalization

**Decisions made this session (do not revisit):**
- Curriculum structured as a progressive skill tree from algebra through topology, mirroring Codebreaker's game-theory pedagogy
- Dual-track design: practical software math (statistics, linear algebra for ML) AND theoretical foundations (toward consciousness-physics formalization)
- Math program integrated into Operation Codebreaker as a core module rather than kept as a separate personal project
- No assumed prerequisites beyond basic arithmetic; practical motivation before abstraction

**Constraints:** Veterans audience with varying math backgrounds. Must integrate with Codebreaker's existing game-theory-based pedagogy. Practical applicability must precede abstract theory.

**Current artifact:** Draft math curriculum skill tree (v1) with dual practical/theoretical tracks. Needs topic mapping and assessment design.

**Open threads requiring resolution:**
1. **[HIGH]** Identify math topics that serve both consciousness-physics formalization and practical software engineering (overlap mapping)
2. **[MEDIUM]** Design mastery assessment gates between curriculum levels
3. **[MEDIUM]** Integration points with Codebreaker's existing game-theory pedagogy and incentive structures (blocked by #1)

**Next action:** Map the topic overlap between practical software math and theoretical consciousness-physics math to determine shared curriculum nodes.
---
