#!/usr/bin/env bash
# Delete the PoC bucket and all its contents, plus local caches.
# Usage: bash extras/cleanup.sh            (reads CLAIMS_BUCKET from .env)
set -euo pipefail
[ -f .env ] && set -a && . ./.env && set +a
BUCKET="${CLAIMS_BUCKET:?CLAIMS_BUCKET not set (run from the project root)}"

read -r -p "Permanently delete s3://$BUCKET and everything in it? [y/N] " ok
[ "$ok" = "y" ] || { echo "aborted"; exit 1; }

aws s3 rb "s3://$BUCKET" --force
rm -rf .local_s3 .rag_index.json .rag_index_mock.json .uploads
echo "Cleaned up. Bedrock has no standing resources in this PoC, so nothing else is billed."
