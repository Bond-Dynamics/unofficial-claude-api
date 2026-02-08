#!/bin/bash
# Weekly Claude conversation sync
# Reads cookies from Firefox, fetches all conversations, saves locally

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
LOG_FILE="$PROJECT_DIR/data/sync.log"

mkdir -p "$PROJECT_DIR/data"

echo "===== Sync started: $(date) =====" >> "$LOG_FILE"

/Users/michaelshaw/miniconda3/bin/python3 "$PROJECT_DIR/examples/fetch_conversations.py" >> "$LOG_FILE" 2>&1
EXIT_CODE=$?

if [ $EXIT_CODE -ne 0 ]; then
    echo "Sync failed with exit code $EXIT_CODE" >> "$LOG_FILE"
    osascript -e 'display notification "Claude conversation sync failed. Check sync.log." with title "Claude Sync"'
else
    echo "Sync completed successfully" >> "$LOG_FILE"
    osascript -e 'display notification "Claude conversations synced successfully." with title "Claude Sync"'
fi

echo "===== Sync ended: $(date) =====" >> "$LOG_FILE"
echo "" >> "$LOG_FILE"
