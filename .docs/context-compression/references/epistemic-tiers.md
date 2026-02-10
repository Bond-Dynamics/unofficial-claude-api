# Epistemic Tiering System

Prevent speculative or unvalidated claims from contaminating continuation prompts. All decisions must be categorized by confidence level.

## Tier Definitions

| Tier | Range | Criteria | Handling |
|------|-------|----------|----------|
| **Validated** | 0.8 - 1.0 | Empirically tested, falsifiable prediction confirmed, documented behavior | MAX-WEIGHT: Treat as fact; heavy priority in constraints and context |
| **Heuristic** | 0.3 - 0.7 | Useful in practice, anecdotally consistent, mechanism not fully understood | MID-WEIGHT: Treat as strong guidance; include but allow re-derivation |
| **Speculative** | 0.0 - 0.2 | Interesting hypothesis, not yet testable, or conflates technical with philosophical | ZERO-WEIGHT: Archive only; exclude from continuation prompts |

## Assignment Guidelines

| Decision Characteristic | Recommended Tier |
|-------------------------|------------------|
| Tested in production, confirmed results | 0.9 - 1.0 |
| Based on documented best practices | 0.8 - 0.9 |
| Worked in similar past projects | 0.5 - 0.7 |
| Team consensus without validation | 0.4 - 0.6 |
| Educated guess, needs validation | 0.2 - 0.3 |
| Speculative, theoretical only | 0.0 - 0.2 |

## Anchor Points

Weights are continuous, not discrete. These ranges are anchor points:

- High-quality Tier 2 heuristic → **0.7**
- Weak Tier 1 claim (validated but edge case) → **0.8**
- Strong Tier 3 speculation (promising but untested) → **0.2** maximum

## Implementation Rules

1. **During Compression:** Assign tier to each decision in the decision log
2. **During Retrieval:** Weight retrieved information according to assigned tier
3. **In Continuation Prompts:** Include only Tier 1 and Tier 2 content by default
4. **Tier 3 Handling:** Archive for reference but exclude from active context unless explicitly requested

## Retrieval Protocol Integration

When retrieving and synthesizing information from archives:

- **Tier 1 claims:** Present as established facts
- **Tier 2 claims:** Present as guidance with "based on prior experience" framing
- **Tier 3 claims:** Only retrieve if explicitly requested; flag as speculative

## Examples

```yaml
decisions:
  - id: D001
    tier: 0.9  # Tier 1: UUID v7 is documented best practice with verified DB benefits
    decision: Use UUID v7 for all resource IDs
    rationale: Sortable, no coordination required, K-sortable for DB performance

  - id: D002
    tier: 0.5  # Tier 2: Works well, team preference, not empirically compared
    decision: Nest tenant context in URL path, not header
    rationale: Cacheable, explicit, debuggable in logs

  - id: D003
    tier: 0.15  # Tier 3: Interesting idea, untested
    decision: Consider GraphQL subscriptions for real-time updates
    rationale: Theoretical fit for use case, no team experience
    # EXCLUDED from continuation prompt, archived only
```
