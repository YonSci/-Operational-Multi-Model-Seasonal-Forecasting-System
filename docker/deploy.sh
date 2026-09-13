#!/usr/bin/env bash
# Kenya MAM Dashboard -- deployment helper
# Usage: ./docker/deploy.sh [build|up|down|logs|restart-backend|test]
set -e

ENV_FILE=".env"
COMPOSE="docker compose -f docker/docker-compose.yml --env-file $ENV_FILE"

if [ ! -f "$ENV_FILE" ]; then
    echo "ERROR: .env file not found. Copy docker/.env.example to .env and fill in your values."
    exit 1
fi

case "${1:-up}" in
  build)
    echo "Building containers..."
    $COMPOSE build --no-cache
    ;;
  up)
    echo "Starting dashboard..."
    $COMPOSE up -d --build
    echo "Waiting for backend to load data (up to 120s)..."
    for i in $(seq 1 24); do
      sleep 5
      if curl -sf http://localhost:8765/health > /dev/null 2>&1; then
        echo "Backend ready!"
        break
      fi
      echo "  waiting... ($((i*5))s)"
    done
    echo "Dashboard: http://localhost"
    echo "API docs:  http://localhost:8765/docs"
    ;;
  down)
    $COMPOSE down
    ;;
  logs)
    $COMPOSE logs -f ${2:-backend}
    ;;
  restart-backend)
    echo "Restarting backend (reloads data)..."
    docker restart mam_backend
    ;;
  test)
    python3 docker/test_deployment.py ${@:2}
    ;;
  *)
    echo "Usage: $0 [build|up|down|logs|restart-backend|test]"
    ;;
esac
