#!/bin/bash
# Weekly Claude conversation sync
# Reads cookies from Firefox, fetches all conversations, saves locally,
# embeds into MongoDB, and replicates MongoDB to GCE.
# PostgreSQL on GCE serves as a secondary backup only.
#
# Schedule: Sundays at 7:00 PM EST (crontab: 0 19 * * 0)
#
# Environment variables:
#   CLAUDE_SYNC_GCP_PUSH=true       Enable GCE MongoDB replication
#   CLAUDE_SYNC_PG_BACKUP=true      Enable PostgreSQL backup on GCE
#   CLAUDE_SYNC_GCE_INSTANCE=name   GCE instance name (default: forge-os)
#   CLAUDE_SYNC_GCE_ZONE=zone       GCE zone (default: us-central1-a)
#   CLAUDE_SYNC_GCE_MONGO=container Remote MongoDB container (default: forge-mongodb)

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
LOG_FILE="$PROJECT_DIR/data/sync.log"
DUMP_DIR="$PROJECT_DIR/data/mongodump"
PYTHON="/Users/michaelshaw/miniconda3/bin/python3"

# Local MongoDB
MONGO_CONTAINER="claude-vectordb"
MONGO_DB="claude_search"

# GCE configuration
GCE_INSTANCE="${CLAUDE_SYNC_GCE_INSTANCE:-forge-os}"
GCE_ZONE="${CLAUDE_SYNC_GCE_ZONE:-us-central1-a}"
GCE_MONGO_CONTAINER="${CLAUDE_SYNC_GCE_MONGO:-forge-mongodb}"
GCP_PUSH_ENABLED="${CLAUDE_SYNC_GCP_PUSH:-false}"
PG_BACKUP_ENABLED="${CLAUDE_SYNC_PG_BACKUP:-false}"

mkdir -p "$PROJECT_DIR/data"

# Redirect all stdout/stderr to log file for the rest of the script.
# osascript talks to the window server directly, unaffected by this.
exec >> "$LOG_FILE" 2>&1

echo "===== Sync started: $(date) ====="

# --- Step 1: Fetch conversations from Claude.ai ---
echo "Fetching conversations..."
$PYTHON "$PROJECT_DIR/examples/fetch_conversations.py"
EXIT_CODE=$?

if [ $EXIT_CODE -ne 0 ]; then
    echo "Fetch failed with exit code $EXIT_CODE"
    osascript -e 'display notification "Claude conversation sync failed. Check sync.log." with title "Claude Sync"'
    echo "===== Sync ended: $(date) ====="
    echo ""
    exit $EXIT_CODE
fi

echo "Fetch completed successfully"

# --- Step 2: Run embedding pipeline if local MongoDB is available ---
if docker exec "$MONGO_CONTAINER" mongosh --quiet --eval "db.runCommand({ping:1})" > /dev/null 2>&1; then
    echo "Running embedding pipeline..."
    $PYTHON -m vectordb.pipeline
    echo "Embedding pipeline finished"
else
    echo "Local MongoDB not running, skipping embedding"
fi

# --- Step 3: Replicate MongoDB to GCE ---
if [ "$GCP_PUSH_ENABLED" = "true" ]; then
    echo "Replicating MongoDB to GCE ($GCE_INSTANCE)..."

    if ! command -v gcloud &> /dev/null; then
        echo "gcloud CLI not found, skipping GCP push"
    elif ! gcloud compute instances describe "$GCE_INSTANCE" --zone="$GCE_ZONE" \
            --format="get(status)" 2>/dev/null | grep -q "RUNNING"; then
        echo "GCE instance $GCE_INSTANCE is not running, skipping push"
    elif ! docker exec "$MONGO_CONTAINER" mongosh --quiet --eval "db.runCommand({ping:1})" > /dev/null 2>&1; then
        echo "Local MongoDB not running, skipping GCP push"
    else
        # Dump local MongoDB
        rm -rf "$DUMP_DIR"
        mkdir -p "$DUMP_DIR"
        docker exec "$MONGO_CONTAINER" mongodump \
            --db="$MONGO_DB" \
            --out="/tmp/mongodump" \
            --quiet

        docker cp "$MONGO_CONTAINER:/tmp/mongodump/$MONGO_DB" "$DUMP_DIR/$MONGO_DB"
        docker exec "$MONGO_CONTAINER" rm -rf /tmp/mongodump

        if [ ! -d "$DUMP_DIR/$MONGO_DB" ]; then
            echo "mongodump produced no output, skipping push"
        else
            DUMP_SIZE=$(du -sh "$DUMP_DIR/$MONGO_DB" | cut -f1)
            echo "Dump size: $DUMP_SIZE"

            # Compress and push to GCE
            ARCHIVE="$DUMP_DIR/claude_search_$(date +%Y%m%d).tar.gz"
            tar -czf "$ARCHIVE" -C "$DUMP_DIR" "$MONGO_DB"

            gcloud compute scp --compress --zone="$GCE_ZONE" \
                "$ARCHIVE" \
                "$GCE_INSTANCE:/tmp/mongodump.tar.gz"

            if [ $? -eq 0 ]; then
                # Extract on GCE, copy into container, restore
                gcloud compute ssh "$GCE_INSTANCE" --zone="$GCE_ZONE" --command="
                    set -e
                    cd /tmp
                    tar -xzf mongodump.tar.gz
                    docker cp /tmp/$MONGO_DB $GCE_MONGO_CONTAINER:/tmp/$MONGO_DB
                    docker exec $GCE_MONGO_CONTAINER mongorestore \
                        --db=$MONGO_DB \
                        --drop \
                        --quiet \
                        /tmp/$MONGO_DB
                    docker exec $GCE_MONGO_CONTAINER rm -rf /tmp/$MONGO_DB
                    rm -rf /tmp/$MONGO_DB /tmp/mongodump.tar.gz
                    echo 'MongoDB restore completed'
                "

                if [ $? -eq 0 ]; then
                    echo "GCE MongoDB restore successful"
                else
                    echo "GCE MongoDB restore failed"
                fi
            else
                echo "Failed to push dump to GCE"
            fi

            # Clean up local dump
            rm -rf "$DUMP_DIR"
        fi
    fi
else
    echo "GCP push disabled (set CLAUDE_SYNC_GCP_PUSH=true to enable)"
fi

# --- Step 4: PostgreSQL backup on GCE (secondary) ---
if [ "$GCP_PUSH_ENABLED" = "true" ] && [ "$PG_BACKUP_ENABLED" = "true" ]; then
    echo "Triggering PostgreSQL backup on GCE..."

    gcloud compute ssh "$GCE_INSTANCE" --zone="$GCE_ZONE" --command="
        if [ -x ~/forge-os/scripts/mongo_to_pg_backup.sh ]; then
            ~/forge-os/scripts/mongo_to_pg_backup.sh >> ~/forge-os/logs/pg_backup.log 2>&1
            echo 'PostgreSQL backup triggered'
        else
            echo 'No mongo_to_pg_backup.sh found, skipping PostgreSQL backup'
        fi
    "
else
    if [ "$GCP_PUSH_ENABLED" = "true" ]; then
        echo "PostgreSQL backup disabled (set CLAUDE_SYNC_PG_BACKUP=true to enable)"
    fi
fi

osascript -e 'display notification "Claude conversations synced successfully." with title "Claude Sync"'

echo "===== Sync ended: $(date) ====="
echo ""
