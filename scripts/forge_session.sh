#!/usr/bin/env bash
# Forge OS Session Workflow — wrapper for the sync pipeline.
#
# Commands:
#   start     --project X              Prepare continuation context -> clipboard
#   compress  --project X              Prepare compression context -> clipboard
#   sync      --project X --project-uuid Y [--file F]  Sync archive to registries
#   flags     --project X              Show pending expedition flags
#   full      --project X --project-uuid Y  Interactive full-cycle walkthrough
#
# Usage:
#   scripts/forge_session.sh start --project "Forge OS"
#   scripts/forge_session.sh sync --project "Forge OS" --project-uuid "abc-123" --file archive.md
#   scripts/forge_session.sh full --project "Forge OS" --project-uuid "abc-123"

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m' # No Color

usage() {
    echo "Usage: forge_session.sh <command> [options]"
    echo ""
    echo "Commands:"
    echo "  start     Prepare continuation context (copies to clipboard)"
    echo "  compress  Prepare compression context (copies to clipboard)"
    echo "  sync      Sync a compression archive to registries"
    echo "  flags     Show pending expedition flags"
    echo "  full      Interactive full-cycle walkthrough"
    echo ""
    echo "Options:"
    echo "  --project <name>       Project display name (required)"
    echo "  --project-uuid <uuid>  Project UUIDv8 (required for sync/full)"
    echo "  --file <path>          Archive file path (for sync)"
    echo "  --conversation-id <id> Conversation UUID"
    echo "  --source-conversation-id <id> Source conversation for lineage"
    echo "  --dry-run              Parse only, don't write to DB"
    exit 1
}

cmd_start() {
    local project=""
    local conversation_id=""

    while [[ $# -gt 0 ]]; do
        case "$1" in
            --project) project="$2"; shift 2 ;;
            --conversation-id) conversation_id="$2"; shift 2 ;;
            *) shift ;;
        esac
    done

    if [[ -z "$project" ]]; then
        echo -e "${RED}Error: --project is required${NC}"
        exit 1
    fi

    echo -e "${BLUE}=== Forge OS: Preparing Continuation ===${NC}"
    echo -e "Project: ${GREEN}$project${NC}"
    echo ""

    local cmd="python3 $SCRIPT_DIR/prepare_continuation.py --project \"$project\""
    if [[ -n "$conversation_id" ]]; then
        cmd="$cmd --conversation-id \"$conversation_id\""
    fi

    eval "$cmd"
}

cmd_compress() {
    local project=""

    while [[ $# -gt 0 ]]; do
        case "$1" in
            --project) project="$2"; shift 2 ;;
            *) shift ;;
        esac
    done

    if [[ -z "$project" ]]; then
        echo -e "${RED}Error: --project is required${NC}"
        exit 1
    fi

    echo -e "${BLUE}=== Forge OS: Preparing Compression ===${NC}"
    echo -e "Project: ${GREEN}$project${NC}"
    echo ""

    python3 "$SCRIPT_DIR/prepare_compression.py" --project "$project"
}

cmd_sync() {
    local project=""
    local project_uuid=""
    local file=""
    local conversation_id=""
    local source_conversation_id=""
    local dry_run=""

    while [[ $# -gt 0 ]]; do
        case "$1" in
            --project) project="$2"; shift 2 ;;
            --project-uuid) project_uuid="$2"; shift 2 ;;
            --file) file="$2"; shift 2 ;;
            --conversation-id) conversation_id="$2"; shift 2 ;;
            --source-conversation-id) source_conversation_id="$2"; shift 2 ;;
            --dry-run) dry_run="--dry-run"; shift ;;
            *) shift ;;
        esac
    done

    if [[ -z "$project" || -z "$project_uuid" ]]; then
        echo -e "${RED}Error: --project and --project-uuid are required${NC}"
        exit 1
    fi

    echo -e "${BLUE}=== Forge OS: Syncing Archive ===${NC}"
    echo -e "Project: ${GREEN}$project${NC}"
    echo -e "UUID:    ${GREEN}$project_uuid${NC}"

    local cmd="python3 $SCRIPT_DIR/sync_compression.py --project \"$project\" --project-uuid \"$project_uuid\""

    if [[ -n "$file" ]]; then
        cmd="$cmd --file \"$file\""
    else
        cmd="$cmd --clipboard"
    fi

    if [[ -n "$conversation_id" ]]; then
        cmd="$cmd --conversation-id \"$conversation_id\""
    fi
    if [[ -n "$source_conversation_id" ]]; then
        cmd="$cmd --source-conversation-id \"$source_conversation_id\""
    fi
    if [[ -n "$dry_run" ]]; then
        cmd="$cmd $dry_run"
    fi

    eval "$cmd"
}

cmd_flags() {
    local project=""
    local category=""

    while [[ $# -gt 0 ]]; do
        case "$1" in
            --project) project="$2"; shift 2 ;;
            --category) category="$2"; shift 2 ;;
            *) shift ;;
        esac
    done

    if [[ -z "$project" ]]; then
        echo -e "${RED}Error: --project is required${NC}"
        exit 1
    fi

    echo -e "${BLUE}=== Forge OS: Expedition Flags ===${NC}"
    echo -e "Project: ${GREEN}$project${NC}"
    echo ""

    local cmd="python3 $SCRIPT_DIR/show_flags.py --project \"$project\""
    if [[ -n "$category" ]]; then
        cmd="$cmd --category \"$category\""
    fi

    eval "$cmd"
}

cmd_full() {
    local project=""
    local project_uuid=""

    while [[ $# -gt 0 ]]; do
        case "$1" in
            --project) project="$2"; shift 2 ;;
            --project-uuid) project_uuid="$2"; shift 2 ;;
            *) shift ;;
        esac
    done

    if [[ -z "$project" || -z "$project_uuid" ]]; then
        echo -e "${RED}Error: --project and --project-uuid are required${NC}"
        exit 1
    fi

    echo -e "${BLUE}╔═══════════════════════════════════════╗${NC}"
    echo -e "${BLUE}║   Forge OS: Full Session Workflow      ║${NC}"
    echo -e "${BLUE}╚═══════════════════════════════════════╝${NC}"
    echo ""
    echo -e "Project: ${GREEN}$project${NC}"
    echo ""

    # Step 1: Prepare continuation
    echo -e "${YELLOW}Step 1/3: Preparing continuation context...${NC}"
    python3 "$SCRIPT_DIR/prepare_continuation.py" --project "$project"
    echo ""

    read -p "$(echo -e ${YELLOW}Press Enter when you've pasted into the new conversation...${NC})" _

    # Step 2: After work is done, check flags before compression
    echo ""
    echo -e "${YELLOW}Step 2/4: Checking pending expedition flags...${NC}"
    python3 "$SCRIPT_DIR/show_flags.py" --project "$project"
    echo ""
    echo -e "${YELLOW}If flags exist, run \"compile expedition\" or \"compile flagged\" in your session before compressing.${NC}"
    read -p "$(echo -e ${YELLOW}Press Enter to continue to compression...${NC})" _

    # Step 3: Prepare compression
    echo ""
    echo -e "${YELLOW}Step 3/4: Preparing compression context...${NC}"
    python3 "$SCRIPT_DIR/prepare_compression.py" --project "$project"
    echo ""

    read -p "$(echo -e ${YELLOW}Press Enter when compression archive is on clipboard...${NC})" _

    # Step 4: Sync archive
    echo ""
    echo -e "${YELLOW}Step 4/4: Syncing archive to registries...${NC}"
    python3 "$SCRIPT_DIR/sync_compression.py" \
        --project "$project" \
        --project-uuid "$project_uuid" \
        --clipboard

    echo ""
    echo -e "${GREEN}=== Session workflow complete ===${NC}"
}

# Main dispatch
if [[ $# -lt 1 ]]; then
    usage
fi

command="$1"
shift

case "$command" in
    start)    cmd_start "$@" ;;
    compress) cmd_compress "$@" ;;
    sync)     cmd_sync "$@" ;;
    flags)    cmd_flags "$@" ;;
    full)     cmd_full "$@" ;;
    *)        usage ;;
esac
