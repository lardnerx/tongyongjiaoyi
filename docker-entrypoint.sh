#!/bin/sh
set -e

echo "Running database migrations..."
cd /app
alembic -c migrations/alembic.ini upgrade head

echo "Starting UMCP server..."
exec "$@"
