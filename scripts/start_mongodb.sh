#!/bin/bash
# Start MongoDB Atlas Local for vector search
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

mkdir -p "$PROJECT_DIR/data/mongodb"

echo "Starting MongoDB Atlas Local..."
docker compose -f "$PROJECT_DIR/docker/docker-compose.yml" up -d

echo "Waiting for MongoDB to be ready..."
until docker exec claude-vectordb mongosh --quiet --eval "db.runCommand({ping:1})" > /dev/null 2>&1; do
    sleep 1
done

echo "MongoDB is ready on localhost:27017"
