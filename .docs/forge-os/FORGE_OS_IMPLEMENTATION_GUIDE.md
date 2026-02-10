# Forge OS: Complete Implementation Guide

## From Claude Projects → Local Cognitive Operating System

---

## TL;DR

**Current State:** 6 Claude projects, sandboxed, manual coordination
**Target State:** Local Forge OS on Mac Studio with:
- All projects as searchable knowledge base
- Multi-model routing (Claude + Gemini + Local)
- Personas replacing projects
- Full programmatic control

**New Projects Needed:** 2 critical (Arbiter, Evaluator), 2 important (Mission Control, Guardian)

---

## Project Mapping: Claude → Local

### Existing Projects → Local Personas

| Claude Project | Local Equivalent | Function |
|----------------|------------------|----------|
| Transmutation Forge | `transmuter` persona | Prompt compilation |
| Reality Compiler | `architect` persona | Consciousness research |
| Cartographer's Codex | `cartographer` persona | Exploration guide |
| Applied Alchemy | `alchemist` persona | Development curriculum |
| CTH-2026 | Folded into `architect` | Research experiments |
| The Nexus | `nexus` persona | Cross-project synthesis |

### New Components (Forge OS Core)

| Component | Function | Type |
|-----------|----------|------|
| **The Arbiter** | Cross-model routing | New (critical) |
| **The Evaluator** | Quality control | New (critical) |
| **Mission Control** | Planning/orchestration | New (important) |
| **The Guardian** | Safety/validation | New (important) |
| **Knowledge Base** | Unified storage | Infrastructure |
| **CLI/API** | User interface | Infrastructure |

---

## Architecture Summary

```
┌─────────────────────────────────────────────────────────────────┐
│                        FORGE OS                                 │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │                    CORE SUBSYSTEMS                        │  │
│  │  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐        │  │
│  │  │ Arbiter │ │Evaluator│ │ Mission │ │Guardian │        │  │
│  │  │(route)  │ │(quality)│ │(plan)   │ │(safety) │        │  │
│  │  └─────────┘ └─────────┘ └─────────┘ └─────────┘        │  │
│  └──────────────────────────────────────────────────────────┘  │
│                              │                                  │
│  ┌───────────────────────────┴──────────────────────────────┐  │
│  │                    PERSONAS                               │  │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐    │  │
│  │  │Cartograph│ │Transmuter│ │ Architect│ │  Nexus   │    │  │
│  │  │   er     │ │          │ │          │ │          │    │  │
│  │  └──────────┘ └──────────┘ └──────────┘ └──────────┘    │  │
│  └──────────────────────────────────────────────────────────┘  │
│                              │                                  │
│  ┌───────────────────────────┴──────────────────────────────┐  │
│  │                 UNIFIED KNOWLEDGE BASE                    │  │
│  │  All project docs, archives, syntheses → searchable      │  │
│  └──────────────────────────────────────────────────────────┘  │
│                              │                                  │
│  ┌───────────────────────────┴──────────────────────────────┐  │
│  │                    MODEL LAYER                            │  │
│  │  Claude API │ Gemini API │ Ollama (Local) │ Specialized  │  │
│  └──────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

---

## Implementation Phases

### Phase 0: Prerequisites (Day 1)

```bash
# Mac Studio setup
brew install python@3.12 ollama redis

# Pull base local models
ollama pull llama3.1:8b
ollama pull llama3.1:70b
ollama pull deepseek-coder:33b

# Create project structure
mkdir -p ~/forge-os/{forge,knowledge,prompts,configs,cli,web}
cd ~/forge-os
python -m venv .venv
source .venv/bin/activate
pip install fastapi uvicorn chromadb anthropic google-generativeai typer rich
```

### Phase 1: Foundation (Week 1-2)

**Goal:** Basic chat with routing

```
□ Project scaffolding
□ Config management (pydantic-settings)
□ Model adapters
  □ AnthropicAdapter (Claude)
  □ OllamaAdapter (local)
□ Basic Arbiter (hardcoded routing rules)
□ CLI chat command
```

**Milestone:** `forge chat "Hello"` routes to appropriate model

### Phase 2: Knowledge Base (Week 3-4)

**Goal:** Import and search all project knowledge

```
□ ChromaDB setup
□ Document ingestion
□ Import script (Claude exports)
□ RAG retrieval
□ CLI knowledge commands
```

**Milestone:** `forge kb search "attention hierarchy"` returns relevant docs

### Phase 3: Full Arbiter (Week 5-6)

**Goal:** Intelligent routing

```
□ Task classifier
□ Model scorer
□ Routing policies
□ Failover logic
□ Cost tracking
□ Health monitoring
```

**Milestone:** Complex tasks auto-route to appropriate model

### Phase 4: Persona System (Week 7-8)

**Goal:** Project parity

```
□ Persona loader
□ Knowledge scoping
□ Context injection
□ Persona switching
□ All personas imported
```

**Milestone:** `forge chat --persona cartographer` works like Claude project

### Phase 5: Evaluator (Week 9-10)

**Goal:** Quality assurance

```
□ Evaluation criteria
□ Quality scoring
□ Gate functions
□ Regression tracking
□ Feedback loops
```

**Milestone:** Outputs validated before return

### Phase 6: Polish (Week 11-12)

**Goal:** Production ready

```
□ Web UI
□ API server
□ Session management
□ Archive system
□ Documentation
```

**Milestone:** Complete local Forge OS operational

---

## File Deliverables

### Provided in This Session

| File | Purpose |
|------|---------|
| `THE_ARBITER_PROJECT_SPEC.md` | Complete Arbiter specification |
| `LOCAL_ARCHITECTURE.md` | Mac Studio deployment guide |
| `IMPLEMENTATION_GUIDE.md` | This document |

### To Create Next

| File | Purpose | Priority |
|------|---------|----------|
| `THE_EVALUATOR_PROJECT_SPEC.md` | Quality control spec | High |
| `MISSION_CONTROL_PROJECT_SPEC.md` | Planning/orchestration | Medium |
| `THE_GUARDIAN_PROJECT_SPEC.md` | Safety layer | Medium |
| `prompts/personas/*.md` | All persona system prompts | High |
| `configs/models.yaml` | Model registry | High |
| `configs/routing.yaml` | Routing policies | High |

---

## Quick Start Script

```bash
#!/bin/bash
# scripts/setup.sh

set -e

echo "═══════════════════════════════════════════════════════════"
echo "  FORGE OS LOCAL SETUP"
echo "═══════════════════════════════════════════════════════════"

# Check prerequisites
command -v python3.12 >/dev/null || { echo "Need Python 3.12+"; exit 1; }
command -v ollama >/dev/null || { echo "Need Ollama"; exit 1; }

# Create structure
echo "Creating directory structure..."
mkdir -p forge/{core,models,knowledge,personas,utils}
mkdir -p knowledge/{projects,archives,synthesis,vectors}
mkdir -p prompts/{personas,routing,evaluation}
mkdir -p configs cli web tests scripts

# Virtual environment
echo "Setting up Python environment..."
python3.12 -m venv .venv
source .venv/bin/activate

# Dependencies
echo "Installing dependencies..."
pip install -q \
  fastapi uvicorn \
  anthropic google-generativeai \
  chromadb \
  typer rich \
  pydantic-settings \
  httpx aiohttp \
  pytest

# Config files
echo "Creating config templates..."
cat > configs/settings.yaml << 'EOF'
forge_os:
  version: "0.1.0"
  default_persona: "cartographer"
  default_model: "claude-sonnet-4"

budget:
  monthly_limit: 50.00
  alert_threshold: 0.80

logging:
  level: INFO
  file: logs/forge.log
EOF

cat > .env.example << 'EOF'
ANTHROPIC_API_KEY=sk-ant-...
GOOGLE_API_KEY=...
OLLAMA_HOST=http://localhost:11434
EOF

# Pull local models
echo "Pulling local models (this may take a while)..."
ollama pull llama3.1:8b

echo ""
echo "═══════════════════════════════════════════════════════════"
echo "  SETUP COMPLETE"
echo "═══════════════════════════════════════════════════════════"
echo ""
echo "Next steps:"
echo "  1. Copy .env.example to .env and add API keys"
echo "  2. Export Claude project files to ~/Downloads/claude_exports/"
echo "  3. Run: python scripts/import_claude_projects.py"
echo "  4. Start: forge chat"
echo ""
```

---

## Migration Checklist

### From Claude Projects

```
□ Export Transmutation Forge knowledge files
□ Export Reality Compiler knowledge files  
□ Export Cartographer's Codex knowledge files
□ Export Applied Alchemy knowledge files
□ Export CTH-2026 knowledge files
□ Export The Nexus knowledge files
□ Export all conversation archives
□ Copy custom instructions for each project
□ Run import script
□ Verify search works across all content
□ Test each persona
```

### Ongoing Workflow

After migration:

1. **New conversations** happen in local Forge OS
2. **Archives** saved locally (optionally sync to cloud backup)
3. **Knowledge** accumulates in local ChromaDB
4. **Claude.ai** still usable for mobile/web access if needed
5. **Routing** automatically picks best model per task

---

## Summary Table

| Forge OS Layer | Component | Status |
|----------------|-----------|--------|
| 6 | Reality Compiler | ✅ Exists (persona) |
| 5 | Meta Attention | 🔨 Building (Forge OS Core) |
| 4 | Cross-Model | 📋 Specified (Arbiter) |
| 3 | Cross-Project | ✅ Exists (Nexus persona) |
| 2 | Project | ✅ Exists (Personas) |
| 1 | Context | ✅ Exists (Conversation) |
| 0 | Token | ✅ Exists (Models) |

**The Arbiter completes Layer 4. The local architecture unifies everything.**

---

## Next Action

1. **Review these specs** — Confirm architecture matches vision
2. **Set up Mac Studio** — Run prerequisites
3. **Start Phase 1** — Build foundation
4. **Export Claude projects** — Prepare for migration

Want me to draft The Evaluator spec next, or start on the actual Python scaffolding?
