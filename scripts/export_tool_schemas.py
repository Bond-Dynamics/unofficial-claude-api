"""Export Forge OS tool schemas for non-MCP LLMs.

Generates:
  1. config/forge_tools_openai.json    — OpenAI function calling format
  2. config/forge_tools_anthropic.json  — Anthropic tool_use format
  3. config/forge_system_prompt.txt     — System prompt template

Usage:
    python scripts/export_tool_schemas.py
"""

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

CONFIG_DIR = PROJECT_ROOT / "config"

# Tool definitions (hand-maintained to avoid importing MCP at export time)
TOOLS = [
    {
        "name": "forge_recall",
        "description": "Search Forge OS memory with attention-weighted scoring across decisions, threads, priming blocks, patterns, conversations, and messages.",
        "parameters": {
            "query": {"type": "string", "description": "What to search for (natural language)", "required": True},
            "project": {"type": "string", "description": "Optional project name to restrict search"},
            "budget": {"type": "integer", "description": "Max characters for context text (default 4000)"},
        },
    },
    {
        "name": "forge_project_context",
        "description": "Get full project state: decisions, threads, flags, stale items, conflicts.",
        "parameters": {
            "project": {"type": "string", "description": "Project display name", "required": True},
            "sections": {"type": "string", "description": "Comma-separated sections: decisions,threads,flags,stale,conflicts"},
        },
    },
    {
        "name": "forge_context_load",
        "description": "One-call conversation bootstrap: project state + optional query recall. Call this at the start of every conversation.",
        "parameters": {
            "project": {"type": "string", "description": "Project display name", "required": True},
            "query": {"type": "string", "description": "Optional search query for additional context recall"},
            "budget": {"type": "integer", "description": "Max chars for combined context (default 6000)"},
        },
    },
    {
        "name": "forge_entanglement",
        "description": "Get cross-project entanglement data: clusters, bridges, loose ends.",
        "parameters": {
            "query": {"type": "string", "description": "Optional text to filter clusters by relevance"},
            "project": {"type": "string", "description": "Optional project name to filter"},
        },
    },
    {
        "name": "forge_trace",
        "description": "Trace the lineage of a conversation through compression hops.",
        "parameters": {
            "conversation_id": {"type": "string", "description": "Conversation identifier (UUID, name, or prefix)", "required": True},
        },
    },
    {
        "name": "forge_alerts",
        "description": "Get system-wide alerts: stale items, conflicts, pending flags, loose ends.",
        "parameters": {},
    },
    {
        "name": "forge_search",
        "description": "Semantic vector search within a specific collection.",
        "parameters": {
            "query": {"type": "string", "description": "Search query text", "required": True},
            "scope": {"type": "string", "description": "Collection: conversations, messages, decisions, patterns", "enum": ["conversations", "messages", "decisions", "patterns"]},
            "limit": {"type": "integer", "description": "Max results (default 10, max 50)"},
        },
    },
    {
        "name": "forge_decide",
        "description": "Register a decision in Forge OS with automatic conflict detection.",
        "parameters": {
            "text": {"type": "string", "description": "Full decision text", "required": True},
            "project": {"type": "string", "description": "Project display name", "required": True},
            "local_id": {"type": "string", "description": "Archive-local ID (e.g. D042)", "required": True},
            "tier": {"type": "number", "description": "Epistemic confidence (0.0-1.0)"},
            "rationale": {"type": "string", "description": "Rationale for the decision"},
        },
    },
    {
        "name": "forge_thread",
        "description": "Track an open question or resolve an existing thread.",
        "parameters": {
            "title": {"type": "string", "description": "Thread title/question", "required": True},
            "project": {"type": "string", "description": "Project display name", "required": True},
            "local_id": {"type": "string", "description": "Archive-local ID (e.g. T007)", "required": True},
            "status": {"type": "string", "description": "Status: open, resolved, blocked", "enum": ["open", "resolved", "blocked"]},
            "priority": {"type": "string", "description": "Priority: high, medium, low", "enum": ["high", "medium", "low"]},
            "resolution": {"type": "string", "description": "Resolution text (required if status=resolved)"},
        },
    },
    {
        "name": "forge_flag",
        "description": "Bookmark an observation or finding for future expedition compilation.",
        "parameters": {
            "description": {"type": "string", "description": "What was observed/flagged", "required": True},
            "project": {"type": "string", "description": "Project display name", "required": True},
            "category": {"type": "string", "description": "Category: inversion, isomorphism, fsd, manifestation, trap, general"},
            "context": {"type": "string", "description": "Optional surrounding context text"},
        },
    },
    {
        "name": "forge_pattern",
        "description": "Store a learned pattern (merges if similar pattern exists).",
        "parameters": {
            "content": {"type": "string", "description": "Pattern content text", "required": True},
            "pattern_type": {"type": "string", "description": "Type: routing, execution, error_recovery, optimization", "required": True},
            "success_score": {"type": "number", "description": "Success score (0.0-1.0)", "required": True},
        },
    },
    {
        "name": "forge_remember",
        "description": "Store a key-value pair in the session scratchpad (TTL: 1 hour).",
        "parameters": {
            "key": {"type": "string", "description": "Key name", "required": True},
            "value": {"type": "string", "description": "Value to store", "required": True},
        },
    },
    {
        "name": "forge_session",
        "description": "Get all key-value pairs stored in the current session scratchpad.",
        "parameters": {},
    },
    {
        "name": "forge_stats",
        "description": "Get Forge OS system overview with collection counts.",
        "parameters": {},
    },
    {
        "name": "forge_projects",
        "description": "List all projects with decision/thread/flag counts.",
        "parameters": {},
    },
]


def _to_json_schema(params):
    """Convert tool parameter definitions to JSON Schema."""
    properties = {}
    required = []

    for name, info in params.items():
        prop = {"type": info["type"], "description": info["description"]}
        if "enum" in info:
            prop["enum"] = info["enum"]
        properties[name] = prop
        if info.get("required"):
            required.append(name)

    schema = {"type": "object", "properties": properties}
    if required:
        schema["required"] = required

    return schema


def export_openai():
    """Generate OpenAI function calling format."""
    functions = []
    for tool in TOOLS:
        func = {
            "type": "function",
            "function": {
                "name": tool["name"],
                "description": tool["description"],
                "parameters": _to_json_schema(tool["parameters"]),
            },
        }
        functions.append(func)
    return functions


def export_anthropic():
    """Generate Anthropic tool_use format."""
    tools = []
    for tool in TOOLS:
        t = {
            "name": tool["name"],
            "description": tool["description"],
            "input_schema": _to_json_schema(tool["parameters"]),
        }
        tools.append(t)
    return tools


def export_system_prompt():
    """Generate a system prompt template for LLMs using Forge OS tools."""
    tool_list = []
    for tool in TOOLS:
        params = ", ".join(
            f"{name}" + (" (required)" if info.get("required") else "")
            for name, info in tool["parameters"].items()
        )
        tool_list.append(f"- {tool['name']}({params}): {tool['description']}")

    return f"""You have access to Forge OS semantic memory tools. Forge OS tracks
decisions, threads, lineage edges, entanglement clusters, priming blocks,
patterns, and expedition flags across multiple projects.

Available tools:
{chr(10).join(tool_list)}

Guidelines:
- Call forge_recall at the start of a conversation to load relevant context.
- When you make a decision, register it with forge_decide.
- When you identify an open question, track it with forge_thread.
- Use forge_flag to bookmark observations for later compilation.
- Use forge_remember to persist session state across messages.
- Check forge_alerts periodically for stale items and conflicts.
"""


def main():
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    openai_path = CONFIG_DIR / "forge_tools_openai.json"
    openai_path.write_text(json.dumps(export_openai(), indent=2))
    print(f"Wrote {openai_path}")

    anthropic_path = CONFIG_DIR / "forge_tools_anthropic.json"
    anthropic_path.write_text(json.dumps(export_anthropic(), indent=2))
    print(f"Wrote {anthropic_path}")

    prompt_path = CONFIG_DIR / "forge_system_prompt.txt"
    prompt_path.write_text(export_system_prompt())
    print(f"Wrote {prompt_path}")


if __name__ == "__main__":
    main()
