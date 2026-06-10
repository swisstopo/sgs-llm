#!/usr/bin/env bash
#
# Rebuild the frontend and publish it to S3 + CloudFront (POC deployment).
# See docs/deployment.md for the full architecture and one-time setup.
#
#   PROFILE=swisstopo ./scripts/deploy-frontend.sh
#
# Does NOT touch config.json (the deployed copy points at the CloudFront
# domain and is managed out-of-band; see docs/deployment.md).
#
# Set PROFILE to the empty string (PROFILE= ./scripts/deploy-frontend.sh) to
# use ambient credentials (e.g. the OIDC role in GitHub Actions).
set -euo pipefail

PROFILE="${PROFILE-swisstopo}"
BUCKET="${BUCKET:-sgs-llm-frontend-259789526488}"
DIST_ID="${DIST_ID:-E2AEIO5QX64WCY}"
DOMAIN="${DOMAIN:-denpw8uo5zpkl.cloudfront.net}"

# Only pass --profile when a profile is set.
PROFILE_ARGS=()
if [[ -n "$PROFILE" ]]; then
  PROFILE_ARGS=(--profile "$PROFILE")
fi

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT/frontend"

echo ">> Building frontend"
npm ci
npm run build

echo ">> Syncing fingerprinted assets (long cache)"
aws s3 sync dist/ "s3://$BUCKET/" --delete "${PROFILE_ARGS[@]}" \
  --cache-control "public,max-age=31536000,immutable" \
  --exclude index.html --exclude config.json

echo ">> Uploading index.html (no-cache)"
aws s3 cp dist/index.html "s3://$BUCKET/index.html" "${PROFILE_ARGS[@]}" \
  --cache-control "no-cache" --content-type "text/html"

echo ">> Invalidating CloudFront"
aws cloudfront create-invalidation --distribution-id "$DIST_ID" --paths '/*' \
  "${PROFILE_ARGS[@]}" --query 'Invalidation.Id' --output text

echo ">> Done -> https://$DOMAIN/"
