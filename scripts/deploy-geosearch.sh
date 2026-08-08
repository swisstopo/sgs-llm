#!/usr/bin/env bash
#
# Build the geodata MCP server container, push it to ECR, and roll the ECS
# service onto it. See geosearch/README.md#deployment.
#
#   PROFILE=swisstopo ./scripts/deploy-geosearch.sh
#
# This is the manual fallback. The normal path is automatic: pushing geosearch
# changes to main runs .github/workflows/geosearch.yml, which calls this same
# script with ambient OIDC credentials.
#
# Set PROFILE to the empty string (PROFILE= ./scripts/deploy-geosearch.sh) to use
# ambient credentials (e.g. the OIDC role in GitHub Actions).
#
# The image needs a prebuilt index, which this script fetches from S3 rather than
# building: `python -m geosearch.build` is ~25 minutes and a few thousand requests
# to geo.admin.ch, and two runs a week apart produce two different indexes. Publish
# one first, from a machine that has just built it:
#
#   python -m geosearch.build
#   aws s3 sync index/ "$(aws cloudformation describe-stacks \
#     --stack-name sgs-llm-geosearch-foundation \
#     --query "Stacks[0].Outputs[?OutputKey=='IndexUri'].OutputValue" --output text)/" --delete
#
# Set INDEX_URI to skip the fetch and build from whatever is already in ./index.
#
# Deploys are immutable: the image is tagged with the commit sha and a NEW task
# definition revision is registered, so rolling back is just pointing the service
# at the previous revision (the script prints how).
set -euo pipefail

PROFILE="${PROFILE-swisstopo}"
REGION="${REGION:-eu-central-1}"
FOUNDATION_STACK="${FOUNDATION_STACK:-sgs-llm-geosearch-foundation}"
CLUSTER="${CLUSTER:-sgs-llm}"
SERVICE="${SERVICE:-sgs-llm-geosearch}"
# Optional: skip the ECS roll and only publish the image.
BUILD_ONLY="${BUILD_ONLY:-0}"
# Optional: set to 1 to build from ./index as it stands, fetching nothing.
USE_LOCAL_INDEX="${USE_LOCAL_INDEX:-0}"

PROFILE_ARGS=()
if [[ -n "$PROFILE" ]]; then
  PROFILE_ARGS=(--profile "$PROFILE")
fi
AWS=(aws "${PROFILE_ARGS[@]}" --region "$REGION")

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

stack_output() {
  "${AWS[@]}" cloudformation describe-stacks --stack-name "$FOUNDATION_STACK" \
    --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue" --output text
}

echo ">> Resolving the ECR repository and index location from stack $FOUNDATION_STACK"
REPO_URI="$(stack_output EcrRepositoryUri)"
STACK_INDEX_URI="$(stack_output IndexUri)"
if [[ -z "$REPO_URI" || "$REPO_URI" == "None" ]]; then
  echo "!! Could not read EcrRepositoryUri from $FOUNDATION_STACK — is the foundation stack deployed?" >&2
  exit 1
fi
REGISTRY="${REPO_URI%%/*}"
INDEX_URI="${INDEX_URI:-$STACK_INDEX_URI}"

if [[ "$USE_LOCAL_INDEX" == "1" ]]; then
  echo ">> USE_LOCAL_INDEX=1 — building from ./index as it stands"
else
  echo ">> Fetching the index from $INDEX_URI"
  "${AWS[@]}" s3 sync "$INDEX_URI" index/
fi

# Fail before the 3 GB build rather than after: a missing index produces an image
# that starts, fails its health check, and gets rolled back twenty minutes later.
if [[ ! -f index/geosearch.duckdb ]]; then
  echo "!! No index at ./index/geosearch.duckdb. Build and publish one first — see the header." >&2
  exit 1
fi
echo "   index: $(du -sh index | cut -f1)"

TAG="${TAG:-$(git rev-parse --short HEAD)$(git diff --quiet || echo '-dirty')}"

# --platform because the task definition pins X86_64 and this is often run from an
# Apple Silicon machine, where the default would be an image ECS cannot start.
echo ">> Building geosearch/Dockerfile  tag: $TAG  (bakes a 2.1 GB model; several minutes)"
docker build --platform linux/amd64 -f geosearch/Dockerfile \
  -t "$REPO_URI:$TAG" -t "$REPO_URI:latest" .

echo ">> Pushing to $REPO_URI"
"${AWS[@]}" ecr get-login-password | docker login --username AWS --password-stdin "$REGISTRY"
docker push "$REPO_URI:$TAG"
docker push "$REPO_URI:latest"

if [[ "$BUILD_ONLY" == "1" ]]; then
  echo ">> BUILD_ONLY=1 — image published, service left untouched"
  exit 0
fi

echo ">> Registering a task definition revision pinned to $TAG"
CURRENT_TD_ARN="$("${AWS[@]}" ecs describe-services --cluster "$CLUSTER" --services "$SERVICE" \
  --query 'services[0].taskDefinition' --output text)"
echo "   current: $CURRENT_TD_ARN"

# Take the running definition, swap the image, drop the read-only fields the
# register call rejects, and register it as a new revision.
"${AWS[@]}" ecs describe-task-definition --task-definition "$CURRENT_TD_ARN" \
  --query 'taskDefinition' --output json > /tmp/sgs-geosearch-td-current.json
python3 - "$REPO_URI:$TAG" <<'PY' > /tmp/sgs-geosearch-td-next.json
import json, sys
image = sys.argv[1]
td = json.load(open('/tmp/sgs-geosearch-td-current.json'))
for key in ('taskDefinitionArn', 'revision', 'status', 'requiresAttributes',
            'compatibilities', 'registeredAt', 'registeredBy', 'deregisteredAt'):
    td.pop(key, None)
for container in td['containerDefinitions']:
    container['image'] = image
json.dump(td, sys.stdout)
PY

NEW_TD_ARN="$("${AWS[@]}" ecs register-task-definition \
  --cli-input-json file:///tmp/sgs-geosearch-td-next.json \
  --query 'taskDefinition.taskDefinitionArn' --output text)"
echo "   new:     $NEW_TD_ARN"

# This service deploys 0/100 rather than 100/200 — `result_id` handles live in one
# process, so two tasks must never run at once. Expect a gap of a minute or two
# here during which the backend's tool calls fail.
echo ">> Rolling the service (brief outage by design — see infra/geosearch-service.yaml)"
"${AWS[@]}" ecs update-service --cluster "$CLUSTER" --service "$SERVICE" \
  --task-definition "$NEW_TD_ARN" --query 'service.deployments[0].[id,status]' --output text

echo ">> Waiting for the service to stabilise (circuit breaker rolls back on failure)"
if "${AWS[@]}" ecs wait services-stable --cluster "$CLUSTER" --services "$SERVICE"; then
  RUNNING_TD="$("${AWS[@]}" ecs describe-services --cluster "$CLUSTER" --services "$SERVICE" \
    --query 'services[0].taskDefinition' --output text)"
  echo ">> Done — running $RUNNING_TD"
  if [[ "$RUNNING_TD" != "$NEW_TD_ARN" ]]; then
    echo "!! The service rolled back to $RUNNING_TD — the new task never became healthy." >&2
    echo "   Check: aws logs tail /ecs/$SERVICE --since 15m ${PROFILE_ARGS[*]} --region $REGION" >&2
    exit 1
  fi
else
  echo "!! Service did not stabilise. Inspect events and logs:" >&2
  echo "   aws ecs describe-services --cluster $CLUSTER --services $SERVICE --query 'services[0].events[:5]'" >&2
  echo "   aws logs tail /ecs/$SERVICE --since 15m" >&2
  exit 1
fi

cat <<EOF

Roll back to the previous revision if needed:
  aws ecs update-service --cluster $CLUSTER --service $SERVICE \\
    --task-definition $CURRENT_TD_ARN ${PROFILE_ARGS[*]} --region $REGION

Note: infra/geosearch-service.yaml's ImageTag parameter is now stale by design
(CI owns the running image). If you ever update that stack, pass the tag that is
actually running so it does not revert: ImageTag=$TAG

This script only swaps the image; it never updates the service stack, and it never
rebuilds the index. A new index needs a fresh 'python -m geosearch.build', an
'aws s3 sync' to $INDEX_URI, and then this script again.
EOF
