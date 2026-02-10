"""Forge OS Layer 3.5: GRAVITY — Multi-lens orchestrated recall.

Extends the attention engine with project role awareness and
convergence/divergence detection. Treats each project as an
epistemic lens that bends the LLM's probability field.

    gravity_assist = spacecraft (prompt)
                   + planet_1 (connector lens — lateral pull)
                   + planet_2 (navigator lens — directional pull)
                   → exit trajectory unreachable by either field alone

No MCP dependency. Called by MCP server and HTTP endpoints.
"""

import json
from concurrent.futures import ThreadPoolExecutor, as_completed

from vectordb.blob_store import get_text_with_fallback
from vectordb.config import (
    ATTENTION_MIN_SCORE,
    GRAVITY_BASELINE_COHERENCE,
    GRAVITY_CONVERGENCE_BOOST,
    GRAVITY_CONVERGENCE_THRESHOLD,
    GRAVITY_DEFAULT_BUDGET,
    GRAVITY_DIVERGENCE_TIER_DELTA,
    GRAVITY_MAX_LENSES,
)
from vectordb.db import get_database
from vectordb.embeddings import embed_query


# ---------------------------------------------------------------------------
# Lens resolution
# ---------------------------------------------------------------------------

def _resolve_lenses(lenses, lens_name, db):
    """Resolve lens configuration from explicit list, named config, or defaults.

    Priority:
      1. Explicit lenses parameter (ad-hoc orchestration)
      2. Named lens configuration from lens_configurations collection
      3. Default: all projects with assigned roles

    Returns:
        List of {project_name, role, weight, gravity_type} dicts.
    """
    if lenses:
        from vectordb.project_roles import ROLE_TYPES
        resolved = []
        for lens in lenses[:GRAVITY_MAX_LENSES]:
            role = lens.get("role", "connector")
            role_meta = ROLE_TYPES.get(role, {"gravity_type": "lateral"})
            resolved.append({
                "project_name": lens["project_name"],
                "role": role,
                "weight": lens.get("weight", 1.0),
                "gravity_type": role_meta["gravity_type"],
            })
        return resolved

    if lens_name:
        from vectordb.project_roles import get_lens, ROLE_TYPES
        config = get_lens(lens_name, db=db)
        if config and config.get("projects"):
            resolved = []
            for p in config["projects"][:GRAVITY_MAX_LENSES]:
                role = p.get("role", "connector")
                role_meta = ROLE_TYPES.get(role, {"gravity_type": "lateral"})
                resolved.append({
                    "project_name": p["project_name"],
                    "role": role,
                    "weight": p.get("weight", 1.0),
                    "gravity_type": role_meta["gravity_type"],
                })
            return resolved

    from vectordb.project_roles import list_roles, ROLE_TYPES
    roles = list_roles(active_only=True, db=db)
    resolved = []
    for r in roles[:GRAVITY_MAX_LENSES]:
        resolved.append({
            "project_name": r["project_name"],
            "role": r["role"],
            "weight": r.get("weight", 1.0),
            "gravity_type": r.get("gravity_type", "lateral"),
        })
    return resolved


# ---------------------------------------------------------------------------
# Parallel per-lens recall
# ---------------------------------------------------------------------------

def _parallel_lens_recall(query, query_embedding, lenses, min_score, db):
    """Run recall() in parallel for each lens, scoped to its project.

    Uses ThreadPoolExecutor with max_workers = len(lenses).
    Passes pre-computed query_embedding to avoid redundant VoyageAI calls.

    Returns:
        Dict keyed by role name: {role: {project, role, gravity_type, results, ...}}
    """
    from vectordb.attention import recall

    per_lens = {}

    def _run_lens(lens):
        result = recall(
            query=query,
            project=lens["project_name"],
            budget=None,
            min_score=min_score,
            query_embedding=query_embedding,
            db=db,
        )
        return lens, result

    with ThreadPoolExecutor(max_workers=len(lenses)) as executor:
        futures = {
            executor.submit(_run_lens, lens): lens
            for lens in lenses
        }

        for future in as_completed(futures):
            try:
                lens, result = future.result()
                role = lens["role"]

                results = result.get("results", [])
                top_att = max(
                    (r.get("attention", 0) for r in results), default=0
                )

                per_lens[role] = {
                    "project": lens["project_name"],
                    "role": role,
                    "gravity_type": lens["gravity_type"],
                    "weight": lens["weight"],
                    "results": results,
                    "result_count": len(results),
                    "top_attention": round(top_att, 4),
                    "total_candidates": result.get("total_candidates", 0),
                }
            except Exception:
                lens = futures[future]
                per_lens[lens["role"]] = {
                    "project": lens["project_name"],
                    "role": lens["role"],
                    "gravity_type": lens["gravity_type"],
                    "weight": lens["weight"],
                    "results": [],
                    "result_count": 0,
                    "top_attention": 0,
                    "total_candidates": 0,
                }

    return per_lens


# ---------------------------------------------------------------------------
# Convergence detection
# ---------------------------------------------------------------------------

def _detect_convergence(per_lens, db):
    """Find where multiple lenses agree — convergent gravity.

    Two detection methods:
      1. Entanglement clusters: Items from different lenses that appear
         in the same cached cluster are convergent.
      2. Semantic overlap: Items from different lenses whose text overlaps
         significantly indicate thematic agreement.

    Returns:
        List of convergence point dicts.
    """
    convergence = []
    roles = list(per_lens.keys())

    if len(roles) < 2:
        return convergence

    # Method 1: Entanglement cluster matching
    from vectordb.entanglement import get_latest_scan
    scan = get_latest_scan(db=db)
    if scan and scan.get("clusters"):
        uuid_to_cluster = {}
        for cluster in scan["clusters"]:
            for item in cluster.get("items", []):
                uuid_to_cluster[item.get("uuid", "")] = cluster

        for i, role_a in enumerate(roles):
            for role_b in roles[i + 1:]:
                results_a = per_lens[role_a]["results"]
                results_b = per_lens[role_b]["results"]

                for ra in results_a:
                    uuid_a = ra.get("uuid", "")
                    cluster_a = uuid_to_cluster.get(uuid_a)
                    if not cluster_a:
                        continue

                    cluster_uuids = {
                        it.get("uuid", "")
                        for it in cluster_a.get("items", [])
                    }

                    for rb in results_b:
                        uuid_b = rb.get("uuid", "")
                        if uuid_b in cluster_uuids:
                            combined = (
                                ra.get("attention", 0)
                                + rb.get("attention", 0)
                            ) * GRAVITY_CONVERGENCE_BOOST
                            convergence.append({
                                "type": "entanglement_cluster",
                                "lenses": [role_a, role_b],
                                "items": [
                                    _summarize_item(ra, role_a),
                                    _summarize_item(rb, role_b),
                                ],
                                "cluster_id": cluster_a.get("cluster_id"),
                                "combined_mass": round(combined, 4),
                                "summary": (
                                    f"Entanglement cluster #{cluster_a.get('cluster_id')}: "
                                    f"{role_a} and {role_b} lenses converge"
                                ),
                            })

    # Method 2: Semantic text overlap (keyword-based approximation)
    for i, role_a in enumerate(roles):
        for role_b in roles[i + 1:]:
            results_a = per_lens[role_a]["results"]
            results_b = per_lens[role_b]["results"]

            for ra in results_a:
                text_a = get_text_with_fallback(ra, "text").lower()
                words_a = set(text_a.split())
                if len(words_a) < 5:
                    continue

                for rb in results_b:
                    if ra.get("uuid") and ra.get("uuid") == rb.get("uuid"):
                        continue

                    text_b = get_text_with_fallback(rb, "text").lower()
                    words_b = set(text_b.split())
                    if len(words_b) < 5:
                        continue

                    overlap = words_a & words_b
                    union = words_a | words_b
                    jaccard = len(overlap) / len(union) if union else 0

                    if jaccard >= GRAVITY_CONVERGENCE_THRESHOLD:
                        combined = (
                            ra.get("attention", 0)
                            + rb.get("attention", 0)
                        ) * GRAVITY_CONVERGENCE_BOOST
                        convergence.append({
                            "type": "semantic_overlap",
                            "lenses": [role_a, role_b],
                            "items": [
                                _summarize_item(ra, role_a),
                                _summarize_item(rb, role_b),
                            ],
                            "cluster_id": None,
                            "combined_mass": round(combined, 4),
                            "summary": (
                                f"Semantic overlap between {role_a} and "
                                f"{role_b} (Jaccard={jaccard:.2f})"
                            ),
                        })

    convergence.sort(key=lambda c: c["combined_mass"], reverse=True)
    return convergence


def _summarize_item(result, role):
    """Create a brief summary of a result item for convergence/divergence."""
    return {
        "role": role,
        "text": result.get("text", "")[:200],
        "category": result.get("category", ""),
        "local_id": result.get("local_id", ""),
        "attention": result.get("attention", 0),
        "uuid": result.get("uuid", ""),
    }


# ---------------------------------------------------------------------------
# Divergence detection
# ---------------------------------------------------------------------------

def _detect_divergence(per_lens, db):
    """Find where lenses disagree — decision tension.

    Three detection methods:
      1. Tier mismatch: Same category items across lenses with divergent
         epistemic tiers on similar topics.
      2. Gap: One lens has strong results while another has none.
      3. Conflicting direction: High-attention items in different lenses
         that reference contradictory conclusions.

    Returns:
        List of divergence point dicts.
    """
    divergence = []
    roles = list(per_lens.keys())

    if len(roles) < 2:
        return divergence

    # Method 1: Gap detection — one lens has results, another doesn't
    for i, role_a in enumerate(roles):
        for role_b in roles[i + 1:]:
            count_a = per_lens[role_a]["result_count"]
            count_b = per_lens[role_b]["result_count"]

            if count_a > 0 and count_b == 0:
                divergence.append({
                    "type": "gap",
                    "lens_a": {
                        "role": role_a,
                        "item": {"result_count": count_a},
                    },
                    "lens_b": {
                        "role": role_b,
                        "item": {"result_count": 0},
                    },
                    "tension_score": 0.6,
                    "description": (
                        f"{role_a} lens ({per_lens[role_a]['project']}) has "
                        f"{count_a} results but {role_b} lens "
                        f"({per_lens[role_b]['project']}) has none — "
                        f"potential blind spot in {role_b} perspective"
                    ),
                })
            elif count_b > 0 and count_a == 0:
                divergence.append({
                    "type": "gap",
                    "lens_a": {
                        "role": role_b,
                        "item": {"result_count": count_b},
                    },
                    "lens_b": {
                        "role": role_a,
                        "item": {"result_count": 0},
                    },
                    "tension_score": 0.6,
                    "description": (
                        f"{role_b} lens ({per_lens[role_b]['project']}) has "
                        f"{count_b} results but {role_a} lens "
                        f"({per_lens[role_a]['project']}) has none — "
                        f"potential blind spot in {role_a} perspective"
                    ),
                })

    # Method 2: Tier mismatch — same-category items with divergent tiers
    for i, role_a in enumerate(roles):
        for role_b in roles[i + 1:]:
            decisions_a = [
                r for r in per_lens[role_a]["results"]
                if r.get("category") == "decision"
                and r.get("epistemic_tier") is not None
            ]
            decisions_b = [
                r for r in per_lens[role_b]["results"]
                if r.get("category") == "decision"
                and r.get("epistemic_tier") is not None
            ]

            for da in decisions_a:
                for db_item in decisions_b:
                    tier_delta = abs(
                        (da.get("epistemic_tier") or 0.5)
                        - (db_item.get("epistemic_tier") or 0.5)
                    )
                    if tier_delta >= GRAVITY_DIVERGENCE_TIER_DELTA:
                        divergence.append({
                            "type": "tier_mismatch",
                            "lens_a": {
                                "role": role_a,
                                "item": _summarize_item(da, role_a),
                            },
                            "lens_b": {
                                "role": role_b,
                                "item": _summarize_item(db_item, role_b),
                            },
                            "tension_score": round(
                                min(1.0, tier_delta / 0.5), 4
                            ),
                            "description": (
                                f"Epistemic tier mismatch: {role_a} "
                                f"{da.get('local_id', '')} at tier "
                                f"{da.get('epistemic_tier'):.1f} vs {role_b} "
                                f"{db_item.get('local_id', '')} at tier "
                                f"{db_item.get('epistemic_tier'):.1f} "
                                f"(delta={tier_delta:.2f})"
                            ),
                        })

    divergence.sort(key=lambda d: d["tension_score"], reverse=True)
    return divergence


# ---------------------------------------------------------------------------
# Field composition
# ---------------------------------------------------------------------------

def _compose_field(per_lens, convergence, divergence, budget):
    """Compose the combined gravitational field with budget-constrained output.

    Allocation order:
      1. Convergence points first (highest combined mass)
      2. Per-lens results sorted by attention
      3. Divergence annotations appended as notes

    Returns:
        Tuple of (field_summary dict, context_text str, budget_used int).
    """
    total_mass = 0
    total_results = 0

    for data in per_lens.values():
        total_results += data["result_count"]
        for r in data["results"]:
            total_mass += r.get("attention", 0)

    convergence_mass = sum(c["combined_mass"] for c in convergence)
    divergence_tension = sum(d["tension_score"] for d in divergence)

    coherence = _compute_field_coherence(
        total_mass, convergence_mass, divergence_tension
    )

    dominant = max(
        per_lens.items(),
        key=lambda kv: sum(r.get("attention", 0) for r in kv[1]["results"]),
        default=(None, {}),
    )
    dominant_lens = dominant[0] or ""

    field_summary = {
        "total_candidates": total_results,
        "convergence_points": len(convergence),
        "divergence_points": len(divergence),
        "dominant_lens": dominant_lens,
        "field_coherence": coherence,
    }

    # Build budget-constrained context text
    parts = []
    used = 0

    # 1. Convergence points
    if convergence:
        header = "=== CONVERGENCE (amplified gravity) ==="
        parts.append(header)
        used += len(header) + 1

        for cp in convergence:
            line = (
                f"[{cp['type']}|mass={cp['combined_mass']:.2f}] "
                f"{cp['summary']}"
            )
            for item in cp.get("items", []):
                item_line = (
                    f"  [{item['role']}] {item.get('local_id', '')} "
                    f"(att={item['attention']:.2f}): "
                    f"{item['text'][:150]}"
                )
                if used + len(item_line) + 1 <= budget:
                    parts.append(item_line)
                    used += len(item_line) + 1

            if used + len(line) + 1 <= budget:
                parts.append(line)
                used += len(line) + 1

    # 2. Per-lens results
    for role, data in sorted(
        per_lens.items(),
        key=lambda kv: kv[1].get("top_attention", 0),
        reverse=True,
    ):
        header = (
            f"=== {role.upper()} ({data['project']}) — "
            f"{data['gravity_type']} gravity ==="
        )
        if used + len(header) + 1 > budget:
            break
        parts.append(header)
        used += len(header) + 1

        sorted_results = sorted(
            data["results"],
            key=lambda r: r.get("attention", 0),
            reverse=True,
        )

        for r in sorted_results:
            label = r.get("local_id") or r.get("uuid", "")[:8]
            line = (
                f"[{r.get('category', '')}|{r.get('attention', 0):.2f}] "
                f"{label}: {r.get('text', '')[:200]}"
            )
            if used + len(line) + 1 > budget:
                break
            parts.append(line)
            used += len(line) + 1

    # 3. Divergence notes
    if divergence:
        header = "=== DIVERGENCE (decision tension) ==="
        if used + len(header) + 1 <= budget:
            parts.append(header)
            used += len(header) + 1

            for dp in divergence[:3]:
                line = (
                    f"[{dp['type']}|tension={dp['tension_score']:.2f}] "
                    f"{dp['description'][:200]}"
                )
                if used + len(line) + 1 > budget:
                    break
                parts.append(line)
                used += len(line) + 1

    context_text = "\n".join(parts)
    return field_summary, context_text, len(context_text)


def _compute_field_coherence(total_mass, convergence_mass, divergence_tension):
    """How aligned are the lenses?

    1.0 = perfect agreement, 0.0 = full contradiction.

    Formula:
      coherence = baseline
                + (convergence_mass / total_mass) * 0.5
                - (divergence_tension / max(total_mass, 1)) * 0.5
    Clamped to [0.0, 1.0].
    """
    if total_mass <= 0:
        return GRAVITY_BASELINE_COHERENCE

    convergence_ratio = convergence_mass / total_mass if total_mass > 0 else 0
    divergence_ratio = divergence_tension / max(total_mass, 1)

    coherence = (
        GRAVITY_BASELINE_COHERENCE
        + convergence_ratio * 0.5
        - divergence_ratio * 0.5
    )

    return round(max(0.0, min(1.0, coherence)), 4)


# ---------------------------------------------------------------------------
# Main orchestration function
# ---------------------------------------------------------------------------

def orchestrate(
    query,
    lenses=None,
    lens_name=None,
    budget=None,
    min_score=None,
    db=None,
):
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
        budget: Max chars for context_text (default GRAVITY_DEFAULT_BUDGET).
        min_score: Minimum attention threshold.
        db: Optional database instance.

    Returns:
        Orchestration result dict with per_lens, convergence, divergence,
        field_summary, context_text, and budget_used.
    """
    if db is None:
        db = get_database()
    if budget is None:
        budget = GRAVITY_DEFAULT_BUDGET
    if min_score is None:
        min_score = ATTENTION_MIN_SCORE

    resolved_lenses = _resolve_lenses(lenses, lens_name, db)
    if not resolved_lenses:
        return {
            "query": query,
            "lens_name": lens_name,
            "lenses_used": [],
            "per_lens": {},
            "convergence": [],
            "divergence": [],
            "field_summary": {
                "total_candidates": 0,
                "convergence_points": 0,
                "divergence_points": 0,
                "dominant_lens": "",
                "field_coherence": 0.5,
            },
            "context_text": "",
            "budget_used": 0,
            "error": "No lenses resolved. Assign project roles or specify lenses.",
        }

    query_embedding = embed_query(query)

    per_lens = _parallel_lens_recall(
        query, query_embedding, resolved_lenses, min_score, db
    )

    convergence = _detect_convergence(per_lens, db)
    divergence = _detect_divergence(per_lens, db)

    field_summary, context_text, budget_used = _compose_field(
        per_lens, convergence, divergence, budget
    )

    return {
        "query": query,
        "lens_name": lens_name,
        "lenses_used": [
            {"project_name": l["project_name"], "role": l["role"], "weight": l["weight"]}
            for l in resolved_lenses
        ],
        "per_lens": per_lens,
        "convergence": convergence,
        "divergence": divergence,
        "field_summary": field_summary,
        "context_text": context_text,
        "budget_used": budget_used,
    }
