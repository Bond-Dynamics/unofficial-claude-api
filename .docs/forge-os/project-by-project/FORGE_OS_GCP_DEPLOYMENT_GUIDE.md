# Forge OS: GCP Deployment Guide

## Practice Environment → Mac Studio Migration

---

## TL;DR

**Strategy:** Deploy to a single Compute Engine VM that mirrors Mac Studio setup exactly. Learn manual server administration. When Mac Studio arrives, copy everything over.

**Cost:** $0/month (Always Free tier) to ~$12/month depending on VM size
**Migration effort:** ~2 hours (mostly DNS/networking)

---

## Architecture: GCP Now → Mac Studio Later

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        GCP (February - June)                            │
│                                                                         │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │              Compute Engine VM (e2-micro, Always Free)             │  │
│  │              Ubuntu 24.04 LTS — 2 shared vCPU, 1 GB RAM          │  │
│  │                                                                   │  │
│  │   ┌─────────────┐  ┌─────────────┐                               │  │
│  │   │  MongoDB    │  │  Forge OS   │                               │  │
│  │   │  (Docker)   │  │  (Kotlin)   │                               │  │
│  │   │  256MB cache│  │   (JVM)     │                               │  │
│  │   └─────────────┘  └─────────────┘                               │  │
│  │        27017           8080                                       │  │
│  │                                                                   │  │
│  │   ~/forge-os/  ← SAME directory structure as Mac                 │  │
│  └───────────────────────────────────────────────────────────────────┘  │
│                              │                                          │
│                       Cloud APIs only                                   │
│              (Claude, Gemini - no local models yet)                    │
│                                                                         │
│  Weekly sync from Mac: mongodump → scp → mongorestore                  │
└──────────────────────────────┼──────────────────────────────────────────┘
                               │
                          mongodump + rsync
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                      Mac Studio (June)                                  │
│                                                                         │
│   SAME setup + local models + PostgreSQL backup:                        │
│                                                                         │
│   ┌─────────────┐  ┌─────────────┐  ┌─────────────┐                   │
│   │  MongoDB    │  │ PostgreSQL  │  │  Forge OS   │                   │
│   │  (primary)  │  │  (backup)   │  │  (Kotlin)   │                   │
│   └─────────────┘  └─────────────┘  └─────────────┘                   │
│                                                                         │
│   ┌─────────────┐  ← NEW: Local LLMs                                   │
│   │   Ollama    │  Llama 3.1 70B, DeepSeek Coder                       │
│   │   (Native)  │  Free, private, fast on M2 Ultra                     │
│   └─────────────┘                                                       │
│                                                                         │
│   ~/forge-os/  ← SAME directory (copied from GCP)                      │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Cost Options

### Option A: Always Free Tier (Recommended)

| Component | Spec | Monthly |
|-----------|------|---------|
| VM | e2-micro (2 shared vCPU, 1 GB) | **$0** |
| Disk | 30 GB standard persistent | **$0** |
| Egress | 1 GB/month to North America | **$0** |
| Snapshots | 5 GB/month | **$0** |
| **Total** | | **$0/month** |

Constraints: 1 instance per billing account, must be in `us-central1`, `us-west1`, or `us-east1`. No static IP (use dynamic DNS or just SSH by instance name). MongoDB runs with 256 MB WiredTiger cache — plenty for the conversation dataset.

### Option B: Small VM (if you outgrow free tier)

| Component | Spec | Monthly |
|-----------|------|---------|
| VM | e2-small (0.5 vCPU, 2 GB) | ~$12 |
| Disk | 30 GB standard | **$0** (free tier) |
| **Total** | | **~$12/month** |

Gives MongoDB 512 MB cache and room for the Kotlin API server alongside it.

---

## Step-by-Step Setup

### Phase 1: Create GCP Resources

```bash
# ════════════════════════════════════════════════════════════════
# CONFIGURE PROJECT
# ════════════════════════════════════════════════════════════════

export PROJECT_ID="forge-os-dev"  # Change to your project
export REGION="us-central1"
export ZONE="us-central1-a"

gcloud config set project $PROJECT_ID
gcloud services enable compute.googleapis.com

# ════════════════════════════════════════════════════════════════
# FIREWALL RULES
# ════════════════════════════════════════════════════════════════

# SSH access
gcloud compute firewall-rules create forge-allow-ssh \
    --allow tcp:22 \
    --source-ranges 0.0.0.0/0

# HTTPS (for API)
gcloud compute firewall-rules create forge-allow-https \
    --allow tcp:443 \
    --source-ranges 0.0.0.0/0

# ════════════════════════════════════════════════════════════════
# CREATE VM (Always Free e2-micro)
# ════════════════════════════════════════════════════════════════

gcloud compute instances create forge-os \
    --zone=$ZONE \
    --machine-type=e2-micro \
    --image-family=ubuntu-2404-lts-amd64 \
    --image-project=ubuntu-os-cloud \
    --boot-disk-size=30GB \
    --boot-disk-type=pd-standard \
    --tags=https-server

# NOTE: No static IP — saves $3/month. Use gcloud compute ssh
# by instance name instead. If you need a stable address later,
# uncomment the following:
#
# gcloud compute addresses create forge-os-ip --region=$REGION
# STATIC_IP=$(gcloud compute addresses describe forge-os-ip \
#     --region=$REGION --format="get(address)")
# gcloud compute instances delete-access-config forge-os --zone=$ZONE \
#     --access-config-name="external-nat" 2>/dev/null || true
# gcloud compute instances add-access-config forge-os --zone=$ZONE \
#     --address=$STATIC_IP

# ════════════════════════════════════════════════════════════════
# SSH IN
# ════════════════════════════════════════════════════════════════

gcloud compute ssh forge-os --zone=$ZONE
```

### Phase 2: Server Setup (run on VM)

```bash
#!/bin/bash
# Execute after SSH into VM

set -e

echo "════════════════════════════════════════════════════════════════"
echo "  FORGE OS SERVER SETUP"
echo "════════════════════════════════════════════════════════════════"

# ════════════════════════════════════════════════════════════════
# SYSTEM PACKAGES
# ════════════════════════════════════════════════════════════════

sudo apt-get update && sudo apt-get upgrade -y

sudo apt-get install -y \
    docker.io \
    docker-compose-v2 \
    git \
    htop \
    tmux

# Docker permissions
sudo usermod -aG docker $USER

# ════════════════════════════════════════════════════════════════
# DIRECTORY STRUCTURE (matches Mac Studio)
# ════════════════════════════════════════════════════════════════

mkdir -p ~/forge-os/{forge-core,forge-cli,forge-server}
mkdir -p ~/forge-os/knowledge/{projects,archives,synthesis}
mkdir -p ~/forge-os/knowledge/projects/{transmutation_forge,reality_compiler,cartographers_codex,applied_alchemy,cth_2026,forge_os,nexus}
mkdir -p ~/forge-os/prompts/personas
mkdir -p ~/forge-os/configs
mkdir -p ~/forge-os/docker
mkdir -p ~/forge-os/scripts
mkdir -p ~/forge-os/logs

# ════════════════════════════════════════════════════════════════
# DOCKER COMPOSE
# ════════════════════════════════════════════════════════════════

cat > ~/forge-os/docker/docker-compose.yaml << 'COMPOSE'
services:
  mongodb:
    image: mongo:7
    container_name: forge-mongodb
    restart: unless-stopped
    command: >
      mongod
        --wiredTigerCacheSizeGB 0.25
        --quiet
    ports:
      - "127.0.0.1:27017:27017"
    volumes:
      - mongo_data:/data/db
    healthcheck:
      test: ["CMD", "mongosh", "--quiet", "--eval", "db.runCommand({ping:1})"]
      interval: 30s
      timeout: 5s
      retries: 3
    deploy:
      resources:
        limits:
          memory: 512M

  postgres:
    image: pgvector/pgvector:pg16
    container_name: forge-postgres
    restart: unless-stopped
    environment:
      POSTGRES_USER: forge
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      POSTGRES_DB: forge_os
    command: >
      postgres
        -c shared_buffers=64MB
        -c work_mem=4MB
        -c maintenance_work_mem=32MB
        -c effective_cache_size=128MB
    ports:
      - "127.0.0.1:5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data
      - ./init.sql:/docker-entrypoint-initdb.d/init.sql
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U forge -d forge_os"]
      interval: 30s
      timeout: 5s
      retries: 3
    deploy:
      resources:
        limits:
          memory: 256M

volumes:
  mongo_data:
  postgres_data:
COMPOSE

# ════════════════════════════════════════════════════════════════
# POSTGRESQL SCHEMA (backup / future migration target)
# ════════════════════════════════════════════════════════════════

cat > ~/forge-os/docker/init.sql << 'SQL'
CREATE EXTENSION IF NOT EXISTS vector;

-- Conversations (mirrors MongoDB conversation_embeddings)
CREATE TABLE conversations (
    conversation_id     UUID PRIMARY KEY,
    name                TEXT,
    summary             TEXT,
    embedding           vector(1024),
    message_count       INTEGER,
    model               VARCHAR(64),
    project_name        VARCHAR(128),
    project_uuid        UUID,
    content_type        VARCHAR(32),
    is_starred          BOOLEAN DEFAULT false,
    platform            VARCHAR(32),
    created_at          TIMESTAMPTZ,
    updated_at          TIMESTAMPTZ,
    metadata            JSONB DEFAULT '{}'
);

CREATE INDEX idx_conv_project ON conversations(project_name);
CREATE INDEX idx_conv_embedding ON conversations
    USING hnsw (embedding vector_cosine_ops);

-- Messages (mirrors MongoDB message_embeddings)
CREATE TABLE messages (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id     UUID REFERENCES conversations(conversation_id),
    message_index       INTEGER,
    sender              VARCHAR(16),
    text                TEXT,
    embedding           vector(1024),
    content_type        VARCHAR(32),
    project_name        VARCHAR(128),
    created_at          TIMESTAMPTZ,
    metadata            JSONB DEFAULT '{}'
);

CREATE INDEX idx_msg_conv ON messages(conversation_id);
CREATE INDEX idx_msg_embedding ON messages
    USING hnsw (embedding vector_cosine_ops);

-- Decision registry (mirrors MongoDB decision_registry)
CREATE TABLE decisions (
    uuid                UUID PRIMARY KEY,
    local_id            VARCHAR(16),
    text                TEXT,
    text_hash           VARCHAR(16),
    embedding           vector(1024),
    project             VARCHAR(128),
    project_uuid        UUID,
    status              VARCHAR(16) DEFAULT 'active',
    epistemic_tier      REAL,
    rationale           TEXT,
    dependencies        TEXT[],
    conflicts_with      UUID[],
    superseded_by       UUID,
    hops_since_validated INTEGER DEFAULT 0,
    last_validated      TIMESTAMPTZ,
    created_at          TIMESTAMPTZ,
    updated_at          TIMESTAMPTZ
);

CREATE INDEX idx_dec_project_status ON decisions(project, status);
CREATE INDEX idx_dec_embedding ON decisions
    USING hnsw (embedding vector_cosine_ops);

-- Thread registry (mirrors MongoDB thread_registry)
CREATE TABLE threads (
    uuid                UUID PRIMARY KEY,
    local_id            VARCHAR(16),
    title               TEXT,
    project             VARCHAR(128),
    project_uuid        UUID,
    status              VARCHAR(16) DEFAULT 'open',
    priority            VARCHAR(8) DEFAULT 'medium',
    blocked_by          TEXT[],
    resolution          TEXT,
    epistemic_tier      REAL,
    hops_since_validated INTEGER DEFAULT 0,
    last_validated      TIMESTAMPTZ,
    created_at          TIMESTAMPTZ,
    updated_at          TIMESTAMPTZ
);

CREATE INDEX idx_thr_project_status ON threads(project, status);

-- Lineage edges (mirrors MongoDB lineage_edges)
CREATE TABLE lineage_edges (
    edge_uuid               UUID PRIMARY KEY,
    source_conversation     UUID,
    target_conversation     UUID,
    compression_tag         VARCHAR(256),
    decisions_carried       UUID[],
    decisions_dropped       UUID[],
    threads_carried         UUID[],
    threads_resolved        UUID[],
    created_at              TIMESTAMPTZ,
    updated_at              TIMESTAMPTZ
);

CREATE INDEX idx_lineage_source ON lineage_edges(source_conversation);
CREATE INDEX idx_lineage_target ON lineage_edges(target_conversation);
CREATE INDEX idx_lineage_tag ON lineage_edges(compression_tag);

-- Compression registry (mirrors MongoDB compression_registry)
CREATE TABLE compressions (
    compression_tag         VARCHAR(256) PRIMARY KEY,
    project                 VARCHAR(128),
    source_conversation     UUID,
    target_conversations    UUID[],
    decisions_captured      TEXT[],
    threads_captured        TEXT[],
    artifacts_captured      TEXT[],
    checksum                VARCHAR(64),
    metadata                JSONB DEFAULT '{}',
    created_at              TIMESTAMPTZ,
    updated_at              TIMESTAMPTZ
);

CREATE INDEX idx_comp_project ON compressions(project);
CREATE INDEX idx_comp_created ON compressions(created_at);
SQL

# ════════════════════════════════════════════════════════════════
# ENVIRONMENT FILE
# ════════════════════════════════════════════════════════════════

cat > ~/forge-os/.env << 'ENV'
# MongoDB (primary)
MONGODB_URI=mongodb://localhost:27017/?directConnection=true

# PostgreSQL (backup)
POSTGRES_PASSWORD=change_this_secure_password
DATABASE_URL=postgresql://forge:change_this_secure_password@localhost:5432/forge_os

# API Keys (add when needed)
# ANTHROPIC_API_KEY=sk-ant-...
# VOYAGE_API_KEY=...
ENV

chmod 600 ~/forge-os/.env

# ════════════════════════════════════════════════════════════════
# 1 GB SWAP (safety net for e2-micro)
# ════════════════════════════════════════════════════════════════

sudo fallocate -l 1G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab

# ════════════════════════════════════════════════════════════════
# START SERVICES
# ════════════════════════════════════════════════════════════════

# Need to re-login for docker group
sudo su - $USER << 'INNER'
cd ~/forge-os/docker
source ../.env
docker compose up -d
INNER

echo ""
echo "════════════════════════════════════════════════════════════════"
echo "  SETUP COMPLETE"
echo "════════════════════════════════════════════════════════════════"
echo ""
echo "Services:"
echo "  MongoDB:    localhost:27017 (primary, 256 MB cache)"
echo "  PostgreSQL: localhost:5432  (backup, 64 MB shared_buffers)"
echo "  Swap:       1 GB (safety net)"
echo ""
echo "Weekly sync from Mac pushes mongodump here automatically."
echo "Next: Edit ~/forge-os/.env with your POSTGRES_PASSWORD"
```

### Phase 3: Backup Script

```bash
cat > ~/forge-os/scripts/backup.sh << 'EOF'
#!/bin/bash
set -e

DATE=$(date +%Y%m%d_%H%M%S)
BACKUP_DIR=~/forge-os/backups
mkdir -p $BACKUP_DIR

echo "Starting backup: $DATE"

# MongoDB
docker exec forge-mongodb mongodump \
    --db=claude_search \
    --out=/tmp/backup \
    --quiet
docker cp forge-mongodb:/tmp/backup/claude_search "$BACKUP_DIR/claude_search_$DATE"
docker exec forge-mongodb rm -rf /tmp/backup
tar -czf "$BACKUP_DIR/claude_search_$DATE.tar.gz" \
    -C "$BACKUP_DIR" "claude_search_$DATE"
rm -rf "$BACKUP_DIR/claude_search_$DATE"

# Cleanup old (keep 4 weeks)
find $BACKUP_DIR -name "*.tar.gz" -mtime +28 -delete

echo "Backup complete: $BACKUP_DIR"
ls -lh "$BACKUP_DIR/"*$DATE*
EOF

chmod +x ~/forge-os/scripts/backup.sh

# Add to crontab (weekly, Mondays at 4am — day after sync)
(crontab -l 2>/dev/null; echo "0 4 * * 1 ~/forge-os/scripts/backup.sh >> ~/forge-os/logs/backup.log 2>&1") | crontab -
```

---

## Migration to Mac Studio (June)

### On GCP: Export Everything

```bash
# Final backup
~/forge-os/scripts/backup.sh

# Full MongoDB dump
docker exec forge-mongodb mongodump --db=claude_search --out=/tmp/final --quiet
docker cp forge-mongodb:/tmp/final/claude_search ~/forge-os-mongo-export
tar -czf ~/forge-os-migration.tar.gz \
    forge-os/docker \
    forge-os/scripts \
    forge-os/.env \
    forge-os-mongo-export
```

### On Your Local Machine: Download

```bash
gcloud compute scp forge-os:~/forge-os-migration.tar.gz . --zone=us-central1-a
```

### On Mac Studio: Import

```bash
# MongoDB is already running locally (claude-vectordb container)
# Just restore the GCE data into it
tar -xzf forge-os-migration.tar.gz
docker cp forge-os-mongo-export claude-vectordb:/tmp/claude_search
docker exec claude-vectordb mongorestore \
    --db=claude_search \
    --drop \
    --quiet \
    /tmp/claude_search
docker exec claude-vectordb rm -rf /tmp/claude_search

# Install Ollama (new capability!)
curl -fsSL https://ollama.com/install.sh | sh
ollama pull llama3.1:70b
ollama pull deepseek-coder:33b
```

---

## Quick Reference

```bash
# SSH in
gcloud compute ssh forge-os --zone=us-central1-a

# Check services
docker ps

# View logs
docker logs forge-mongodb

# Restart
docker compose -f ~/forge-os/docker/docker-compose.yaml restart

# Backup now
~/forge-os/scripts/backup.sh

# Connect to database
docker exec -it forge-mongodb mongosh claude_search

# Check disk usage
df -h
docker system df
```
