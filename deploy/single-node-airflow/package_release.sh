#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
DIST_DIR="${PROJECT_ROOT}/dist"
VERSION="${1:-single-node}"
CHUNK_SIZE_MB="${CHUNK_SIZE_MB:-20}"

mkdir -p "${DIST_DIR}"

ARCHIVE="${DIST_DIR}/ingestion-framework-${VERSION}.tar.gz"

tar \
  --exclude=".DS_Store" \
  --exclude=".env" \
  --exclude=".git" \
  --exclude=".pytest_cache" \
  --exclude=".venv" \
  --exclude="__pycache__" \
  --exclude="*.pyc" \
  --exclude="*.egg-info" \
  --exclude="data/audit/*.db" \
  --exclude="data/metadata/*.db" \
  --exclude="data/output" \
  --exclude="deploy/single-node-airflow/.env" \
  --exclude="deploy/single-node-airflow/generated" \
  --exclude="dist" \
  -czf "${ARCHIVE}" \
  -C "${PROJECT_ROOT}/.." \
  "$(basename "${PROJECT_ROOT}")"

rm -f "${ARCHIVE}".part-*
split -b "${CHUNK_SIZE_MB}m" -d -a 3 "${ARCHIVE}" "${ARCHIVE}.part-"

cat > "${DIST_DIR}/README-transfer.txt" <<EOF
Transfer package: $(basename "${ARCHIVE}")

Preferred:
  Copy $(basename "${ARCHIVE}") to the Ubuntu server.

If email/file-transfer limits require chunks:
  Copy all files named $(basename "${ARCHIVE}").part-* to the same directory on the Ubuntu server.
  Reassemble:
    cat $(basename "${ARCHIVE}").part-* > $(basename "${ARCHIVE}")

Extract on Ubuntu:
  tar -xzf $(basename "${ARCHIVE}")
  cd ingestion-framework/deploy/single-node-airflow
  python3 install_platform.py
  docker compose --env-file .env up -d --build

Notes:
  The archive intentionally excludes the Mac .venv, caches, generated secrets, local databases, and output data.
  Docker images and Python dependencies are downloaded or built from inside the client's network during docker compose build/up.
EOF

echo "Created ${ARCHIVE}"
echo "Created chunks: ${ARCHIVE}.part-*"
du -sh "${ARCHIVE}" "${ARCHIVE}".part-* "${DIST_DIR}/README-transfer.txt"
