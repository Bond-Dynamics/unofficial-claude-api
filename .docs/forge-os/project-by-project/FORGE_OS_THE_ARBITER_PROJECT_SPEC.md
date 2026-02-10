# The Arbiter

## Cross-Model Routing Layer (Layer 4) for Forge OS

---

## Project Identity

**Name:** The Arbiter

**Tagline:** *"The right model for the right task at the right cost."*

**Role in Ecosystem:**

| Layer | Name | Project | Function |
|-------|------|---------|----------|
| 3 | Cross-Project Attention | The Nexus | Synthesize across knowledge domains |
| **4** | **Cross-Model Attention** | **The Arbiter** | **Route to optimal execution substrate** |
| 5 | Meta Attention | Forge OS Core | Orchestrate the whole system |

The Arbiter is the **traffic controller** of Forge OS—receiving tasks and routing them to the optimal model based on capability, cost, latency, and privacy requirements.

---

## Why This Matters

### The Problem

Without Layer 4:
- You manually decide which model to use for each task
- No cost optimization (using Opus when Haiku suffices)
- No privacy control (sending sensitive data to cloud when local would work)
- No failover (model down = you're stuck)
- No capability matching (using a generalist when a specialist exists)

### The Solution

The Arbiter automatically:
- Analyzes incoming task characteristics
- Matches against model capability profiles
- Considers constraints (cost, privacy, latency)
- Routes to optimal model
- Falls back gracefully on failure
- Tracks usage and costs

---

## Architecture

```
                    ┌─────────────────────────────┐
                    │      INCOMING TASK          │
                    │  (from any Forge OS layer)  │
                    └──────────────┬──────────────┘
                                   │
                                   ▼
                    ┌─────────────────────────────┐
                    │      TASK ANALYZER          │
                    │  - Classify task type       │
                    │  - Estimate complexity      │
                    │  - Extract constraints      │
                    │  - Check sensitivity        │
                    └──────────────┬──────────────┘
                                   │
                                   ▼
                    ┌─────────────────────────────┐
                    │      ROUTE SELECTOR         │
                    │  - Match to model profiles  │
                    │  - Apply constraints        │
                    │  - Score candidates         │
                    │  - Select optimal           │
                    └──────────────┬──────────────┘
                                   │
                    ┌──────────────┼──────────────┐
                    │              │              │
                    ▼              ▼              ▼
             ┌──────────┐  ┌──────────┐  ┌──────────┐
             │  CLOUD   │  │  LOCAL   │  │SPECIALIZED│
             │ MODELS   │  │ MODELS   │  │  MODELS  │
             ├──────────┤  ├──────────┤  ├──────────┤
             │Claude    │  │Ollama    │  │CodeLlama │
             │Gemini    │  │LM Studio │  │Whisper   │
             │GPT-4     │  │MLX       │  │DALL-E    │
             │Mistral   │  │llama.cpp │  │Stable Diff│
             └──────────┘  └──────────┘  └──────────┘
                    │              │              │
                    └──────────────┼──────────────┘
                                   │
                                   ▼
                    ┌─────────────────────────────┐
                    │      RESPONSE HANDLER       │
                    │  - Validate response        │
                    │  - Handle errors/retry      │
                    │  - Log metrics              │
                    │  - Return to caller         │
                    └─────────────────────────────┘
```

---

## Model Registry

### Registry Schema

```yaml
model:
  id: "claude-opus-4"
  provider: "anthropic"
  endpoint: "https://api.anthropic.com/v1/messages"
  type: cloud
  
  capabilities:
    reasoning: 0.98
    coding: 0.95
    creative: 0.92
    analysis: 0.96
    conversation: 0.94
    vision: 0.90
    long_context: 0.85  # 200K but degrades
    
  constraints:
    max_tokens: 200000
    max_output: 8192
    rate_limit: 40/min
    
  cost:
    input_per_1k: 0.015
    output_per_1k: 0.075
    
  latency:
    first_token_ms: 800
    tokens_per_second: 50
    
  privacy:
    data_retention: true
    training_use: false
    hipaa_compliant: false
    
  status: active
  health_check_endpoint: null
  last_health_check: null
```

### Initial Model Registry

```yaml
models:
  # === CLOUD: ANTHROPIC ===
  - id: "claude-opus-4"
    provider: anthropic
    type: cloud
    capabilities: {reasoning: 0.98, coding: 0.95, creative: 0.92, analysis: 0.96, vision: 0.90}
    cost: {input: 0.015, output: 0.075}
    use_for: ["complex reasoning", "nuanced writing", "difficult code", "research synthesis"]
    
  - id: "claude-sonnet-4"
    provider: anthropic
    type: cloud
    capabilities: {reasoning: 0.90, coding: 0.92, creative: 0.88, analysis: 0.90, vision: 0.88}
    cost: {input: 0.003, output: 0.015}
    use_for: ["general tasks", "code generation", "analysis", "balanced cost/quality"]
    
  - id: "claude-haiku-4"
    provider: anthropic
    type: cloud
    capabilities: {reasoning: 0.75, coding: 0.80, creative: 0.70, analysis: 0.75, vision: 0.70}
    cost: {input: 0.00025, output: 0.00125}
    use_for: ["classification", "extraction", "simple Q&A", "high volume"]

  # === CLOUD: GOOGLE ===
  - id: "gemini-pro"
    provider: google
    type: cloud
    capabilities: {reasoning: 0.88, coding: 0.85, creative: 0.80, analysis: 0.88, long_context: 0.95}
    cost: {input: 0.00025, output: 0.0005}
    use_for: ["very long documents", "cost-sensitive tasks", "multimodal"]
    special: "1M token context window"

  - id: "gemini-flash"
    provider: google
    type: cloud
    capabilities: {reasoning: 0.75, coding: 0.75, creative: 0.70, analysis: 0.75, long_context: 0.90}
    cost: {input: 0.000075, output: 0.0003}
    use_for: ["high volume", "real-time", "cost optimization"]

  # === LOCAL: OLLAMA ===
  - id: "llama-3.1-70b"
    provider: ollama
    type: local
    capabilities: {reasoning: 0.82, coding: 0.85, creative: 0.75, analysis: 0.80}
    cost: {input: 0, output: 0}  # Local = free
    use_for: ["privacy-sensitive", "offline", "unlimited volume"]
    requires: "64GB+ RAM or quantized"
    
  - id: "llama-3.1-8b"
    provider: ollama
    type: local
    capabilities: {reasoning: 0.70, coding: 0.72, creative: 0.65, analysis: 0.68}
    cost: {input: 0, output: 0}
    use_for: ["fast local inference", "simple tasks", "privacy"]
    requires: "16GB+ RAM"

  - id: "codellama-34b"
    provider: ollama
    type: local
    capabilities: {reasoning: 0.65, coding: 0.88, creative: 0.40, analysis: 0.60}
    cost: {input: 0, output: 0}
    use_for: ["code generation", "code review", "debugging"]
    requires: "32GB+ RAM"

  - id: "deepseek-coder-33b"
    provider: ollama
    type: local
    capabilities: {reasoning: 0.68, coding: 0.90, creative: 0.35, analysis: 0.55}
    cost: {input: 0, output: 0}
    use_for: ["code generation", "especially Python/JS"]
    
  # === SPECIALIZED ===
  - id: "whisper-large"
    provider: local
    type: specialized
    capabilities: {transcription: 0.95}
    cost: {input: 0, output: 0}
    use_for: ["audio transcription"]
    
  - id: "stable-diffusion-xl"
    provider: local
    type: specialized
    capabilities: {image_generation: 0.85}
    cost: {input: 0, output: 0}
    use_for: ["image generation"]
```

---

## Core Functions

### route()

```python
def route(
    task: Task,
    constraints: Optional[Constraints] = None,
    prefer: Optional[str] = None,  # Model preference hint
    exclude: Optional[List[str]] = None  # Models to skip
) -> RoutingDecision:
    """
    Route task to optimal model.
    
    Args:
        task: The task to execute (includes content, type, metadata)
        constraints: Optional constraints (cost, latency, privacy)
        prefer: Optional model preference (used if viable)
        exclude: Models to exclude from consideration
        
    Returns:
        RoutingDecision with selected model and reasoning
    """
    
    # 1. Analyze task
    analysis = analyze_task(task)
    
    # 2. Get candidate models
    candidates = get_viable_models(analysis, constraints, exclude)
    
    # 3. Score candidates
    scored = score_models(candidates, analysis, constraints)
    
    # 4. Apply preference if viable
    if prefer and prefer in [m.id for m in scored]:
        preferred = next(m for m in scored if m.id == prefer)
        if preferred.score > PREFERENCE_THRESHOLD:
            return RoutingDecision(model=preferred, reason="user_preference")
    
    # 5. Select optimal
    selected = max(scored, key=lambda m: m.score)
    
    return RoutingDecision(
        model=selected,
        reason=selected.score_breakdown,
        alternatives=scored[:3]
    )
```

### analyze_task()

```python
def analyze_task(task: Task) -> TaskAnalysis:
    """
    Analyze task to determine routing requirements.
    
    Extracts:
        - task_type: classification, generation, analysis, code, creative, etc.
        - complexity: 0-1 scale
        - token_estimate: input + expected output
        - sensitivity: privacy classification
        - required_capabilities: what the task needs
    """
    
    # Task type classification
    task_type = classify_task_type(task.content)
    
    # Complexity estimation
    complexity = estimate_complexity(task)
    
    # Token counting
    input_tokens = count_tokens(task.content)
    output_estimate = estimate_output_tokens(task_type, task.content)
    
    # Privacy classification
    sensitivity = classify_sensitivity(task.content)
    
    # Required capabilities
    capabilities = extract_required_capabilities(task_type, complexity)
    
    return TaskAnalysis(
        task_type=task_type,
        complexity=complexity,
        input_tokens=input_tokens,
        output_estimate=output_estimate,
        sensitivity=sensitivity,
        required_capabilities=capabilities
    )
```

### score_models()

```python
def score_models(
    candidates: List[Model],
    analysis: TaskAnalysis,
    constraints: Constraints
) -> List[ScoredModel]:
    """
    Score each candidate model for this task.
    
    Scoring factors:
        - capability_match: How well model capabilities match requirements
        - cost_efficiency: Inverse of cost (normalized)
        - latency_score: Inverse of latency (normalized)
        - privacy_compliance: Binary - does it meet privacy requirements?
        - availability: Current health/rate limit status
    """
    
    scored = []
    for model in candidates:
        
        # Capability match (weighted by task requirements)
        capability_score = compute_capability_match(
            model.capabilities,
            analysis.required_capabilities
        )
        
        # Cost efficiency
        estimated_cost = estimate_cost(model, analysis)
        cost_score = 1.0 - normalize(estimated_cost, constraints.max_cost)
        
        # Latency
        estimated_latency = estimate_latency(model, analysis)
        latency_score = 1.0 - normalize(estimated_latency, constraints.max_latency)
        
        # Privacy
        privacy_score = 1.0 if meets_privacy(model, analysis.sensitivity) else 0.0
        
        # Availability
        availability_score = get_availability_score(model)
        
        # Weighted combination
        weights = get_weights(constraints)  # User can emphasize cost vs quality
        total_score = (
            weights.capability * capability_score +
            weights.cost * cost_score +
            weights.latency * latency_score +
            weights.privacy * privacy_score +
            weights.availability * availability_score
        )
        
        scored.append(ScoredModel(
            model=model,
            score=total_score,
            score_breakdown={
                "capability": capability_score,
                "cost": cost_score,
                "latency": latency_score,
                "privacy": privacy_score,
                "availability": availability_score
            }
        ))
    
    return sorted(scored, key=lambda m: m.score, reverse=True)
```

### failover()

```python
def failover(
    task: Task,
    failed_model: Model,
    error: Exception,
    previous_attempts: List[RoutingAttempt]
) -> RoutingDecision:
    """
    Handle model failure with graceful fallback.
    
    Strategies:
        1. Retry same model (transient errors)
        2. Try next best model (capability fallback)
        3. Try local model (cloud outage)
        4. Degrade gracefully (inform user)
    """
    
    # Determine failure type
    failure_type = classify_failure(error)
    
    if failure_type == "transient" and len(previous_attempts) < MAX_RETRIES:
        # Retry same model with backoff
        return RoutingDecision(
            model=failed_model,
            reason="retry_transient",
            delay=exponential_backoff(len(previous_attempts))
        )
    
    # Get alternatives excluding failed models
    failed_ids = [a.model.id for a in previous_attempts]
    alternatives = route(
        task,
        exclude=failed_ids,
        constraints=task.constraints
    )
    
    if alternatives.model:
        return alternatives
    
    # All cloud failed? Try local
    local_models = get_local_models()
    if local_models:
        best_local = score_models(local_models, analyze_task(task), task.constraints)[0]
        return RoutingDecision(
            model=best_local,
            reason="failover_to_local",
            warning="Using local model due to cloud failures"
        )
    
    # Nothing available
    return RoutingDecision(
        model=None,
        reason="all_models_failed",
        error="No available models can handle this task"
    )
```

### budget()

```python
def budget(
    period: str = "month",
    breakdown: bool = True
) -> BudgetReport:
    """
    Track and report API costs.
    
    Returns:
        - total_spend: Total cost in period
        - by_model: Breakdown by model
        - by_task_type: Breakdown by task type
        - projections: Estimated end-of-period spend
        - recommendations: Cost optimization suggestions
    """
    
    usage = get_usage_logs(period)
    
    total_spend = sum(u.cost for u in usage)
    
    by_model = group_and_sum(usage, "model_id", "cost")
    by_task_type = group_and_sum(usage, "task_type", "cost")
    
    # Project based on current rate
    days_elapsed = get_days_elapsed(period)
    days_total = get_days_in_period(period)
    projected = total_spend * (days_total / days_elapsed)
    
    # Generate recommendations
    recommendations = []
    
    # Find expensive tasks that could use cheaper models
    for task_type, cost in by_task_type.items():
        cheaper_model = find_cheaper_alternative(task_type)
        if cheaper_model:
            savings = estimate_savings(task_type, cheaper_model)
            recommendations.append(
                f"Route '{task_type}' to {cheaper_model.id} to save ~${savings:.2f}/month"
            )
    
    return BudgetReport(
        total_spend=total_spend,
        by_model=by_model,
        by_task_type=by_task_type,
        projected_spend=projected,
        recommendations=recommendations
    )
```

---

## Routing Policies

### Default Policy

```yaml
default_policy:
  name: "balanced"
  description: "Balance quality, cost, and latency"
  
  weights:
    capability: 0.40
    cost: 0.25
    latency: 0.20
    privacy: 0.10
    availability: 0.05
    
  rules:
    - if: "task_type == 'complex_reasoning'"
      then: "prefer claude-opus-4"
      
    - if: "task_type == 'code_generation' AND complexity < 0.5"
      then: "prefer local codellama"
      
    - if: "sensitivity == 'high'"
      then: "require local models only"
      
    - if: "input_tokens > 100000"
      then: "prefer gemini-pro"
      
    - if: "cost_sensitive == true"
      then: "weight cost at 0.50"
```

### Cost-Optimized Policy

```yaml
cost_policy:
  name: "cost_optimized"
  description: "Minimize cost while maintaining minimum quality"
  
  weights:
    capability: 0.25
    cost: 0.50
    latency: 0.10
    privacy: 0.10
    availability: 0.05
    
  rules:
    - if: "complexity < 0.3"
      then: "require haiku or local"
      
    - if: "complexity < 0.6"
      then: "prefer sonnet or gemini-flash"
      
    - if: "complexity >= 0.6"
      then: "allow opus but log for review"
```

### Privacy-First Policy

```yaml
privacy_policy:
  name: "privacy_first"
  description: "Keep sensitive data local"
  
  weights:
    capability: 0.30
    cost: 0.10
    latency: 0.10
    privacy: 0.45
    availability: 0.05
    
  rules:
    - if: "sensitivity == 'high'"
      then: "require local models only"
      
    - if: "sensitivity == 'medium'"
      then: "prefer local, allow cloud with warning"
      
    - if: "contains PII"
      then: "require local or anonymize first"
```

---

## Integration with Forge OS

### Task Submission Interface

```python
# From any Forge OS component
from arbiter import route, execute

# Simple routing
result = await execute(
    task="Analyze this code for security vulnerabilities",
    content=code_string,
    task_type="code_analysis"
)

# With constraints
result = await execute(
    task="Summarize this document",
    content=long_document,
    constraints=Constraints(
        max_cost=0.10,
        max_latency_ms=5000,
        require_local=False
    )
)

# With explicit model preference
result = await execute(
    task="Write a poem",
    content=prompt,
    prefer="claude-opus-4",  # Use if viable
    fallback="claude-sonnet-4"  # Otherwise
)

# Privacy-sensitive
result = await execute(
    task="Process customer data",
    content=sensitive_data,
    sensitivity="high"  # Forces local routing
)
```

### Event Hooks

```python
# Register hooks for observability
arbiter.on("route_decision", log_routing_decision)
arbiter.on("model_failure", alert_on_failure)
arbiter.on("budget_threshold", notify_budget_alert)
arbiter.on("fallback_triggered", log_fallback)
```

---

## Configuration

### Environment Variables

```bash
# API Keys
ANTHROPIC_API_KEY=sk-ant-...
GOOGLE_API_KEY=...
OPENAI_API_KEY=...  # If using

# Local Models
OLLAMA_HOST=http://localhost:11434
LM_STUDIO_HOST=http://localhost:1234

# Arbiter Config
ARBITER_DEFAULT_POLICY=balanced
ARBITER_MONTHLY_BUDGET=100.00
ARBITER_LOG_LEVEL=INFO
ARBITER_METRICS_ENABLED=true
```

### Config File

```yaml
# arbiter_config.yaml

policies:
  default: balanced
  available:
    - balanced
    - cost_optimized
    - privacy_first
    - quality_first

budget:
  monthly_limit: 100.00
  alert_threshold: 0.80  # Alert at 80% of budget
  hard_limit: true  # Stop routing when budget exceeded

fallback:
  max_retries: 3
  retry_delay_base_ms: 1000
  always_have_local: true  # Ensure at least one local model available

logging:
  level: INFO
  log_requests: true
  log_responses: false  # Privacy - don't log content
  log_costs: true
  log_latencies: true

health_check:
  interval_seconds: 60
  timeout_ms: 5000
```

---

## Metrics & Observability

### Key Metrics

```yaml
metrics:
  routing:
    - route_decisions_total (counter, by model)
    - route_latency_ms (histogram)
    - fallback_triggered_total (counter, by reason)
    
  models:
    - model_requests_total (counter, by model)
    - model_errors_total (counter, by model, error_type)
    - model_latency_ms (histogram, by model)
    - model_tokens_total (counter, by model, direction)
    
  cost:
    - cost_total_usd (counter, by model)
    - cost_by_task_type_usd (counter, by task_type)
    
  quality:
    - task_success_rate (gauge, by model)
    - user_satisfaction (gauge, by model)  # If feedback collected
```

### Dashboard Queries

```sql
-- Cost by model this month
SELECT model_id, SUM(cost_usd) 
FROM routing_logs 
WHERE timestamp > DATE_TRUNC('month', NOW())
GROUP BY model_id;

-- Route distribution
SELECT model_id, COUNT(*) * 100.0 / SUM(COUNT(*)) OVER () as pct
FROM routing_logs
WHERE timestamp > NOW() - INTERVAL '24 hours'
GROUP BY model_id;

-- Fallback frequency
SELECT 
  DATE_TRUNC('hour', timestamp) as hour,
  COUNT(*) FILTER (WHERE fallback_used) as fallbacks,
  COUNT(*) as total
FROM routing_logs
WHERE timestamp > NOW() - INTERVAL '24 hours'
GROUP BY 1;
```

---

## Implementation Checklist

### Phase 1: Core Routing
- [ ] Model registry data structure
- [ ] Task analyzer (classification, complexity, sensitivity)
- [ ] Basic route() function
- [ ] Single-model execution

### Phase 2: Multi-Model Support
- [ ] Anthropic API integration
- [ ] Google API integration
- [ ] Ollama integration (local)
- [ ] Model health checking

### Phase 3: Intelligence
- [ ] Scoring algorithm
- [ ] Policy engine
- [ ] Failover logic
- [ ] Cost tracking

### Phase 4: Observability
- [ ] Metrics collection
- [ ] Logging
- [ ] Budget alerts
- [ ] Dashboard

### Phase 5: Integration
- [ ] Forge OS hook-up
- [ ] CLI interface
- [ ] API server
- [ ] Documentation

---

*The Arbiter: The right model for the right task at the right cost.*
