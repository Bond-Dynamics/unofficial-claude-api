#!/bin/bash
# Stop MongoDB Atlas Local
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

echo "Stopping MongoDB Atlas Local..."
docker compose -f "$PROJECT_DIR/docker/docker-compose.yml" down

echo "MongoDB stopped."
