#!/usr/bin/env bash
#
# Build the agent backend container, push it to ECR, and roll the ECS service
# onto it. See docs/deployment.md#backend-deployment for the architecture and the
# one-time infrastructure setup.
#
#   PROFILE=swisstopo ./scripts/deploy-backend.sh
#
# This is the manual fallback. The normal path is automatic: pushing to main
# runs .github/workflows/backend.yml, which calls this same script with ambient
# OIDC credentials.
#
# Set PROFILE to the empty string (PROFILE= ./scripts/deploy-backend.sh) to use
# ambient credentials (e.g. the OIDC role in GitHub Actions).
#
# Deploys are immutable: the image is tagged with the commit sha and a NEW task
# definition revision is registered, so rolling back is just pointing the service
# at the previous revision (the script prints how).
set -euo pipefail

PROFILE="${PROFILE-swisstopo}"
REGION="${REGION:-eu-central-1}"
FOUNDATION_STACK="${FOUNDATION_STACK:-sgs-llm-backend-foundation}"
CLUSTER="${CLUSTER:-sgs-llm}"
SERVICE="${SERVICE:-sgs-llm-backend}"
# Optional: skip the ECS roll and only publish the image.
BUILD_ONLY="${BUILD_ONLY:-0}"

PROFILE_ARGS=()
if [[ -n "$PROFILE" ]]; then
  PROFILE_ARGS=(--profile "$PROFILE")
fi
# ${x[@]+"${x[@]}"}: bash 3.2 (macOS) treats an empty array as unset under `set -u`.
AWS=(aws ${PROFILE_ARGS[@]+"${PROFILE_ARGS[@]}"} --region "$REGION")

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# The real backend replaces the mock-agent the moment it lands a Dockerfile —
# no infrastructure change, no workflow edit.
if [[ -f backend/Dockerfile ]]; then
  DOCKERFILE="backend/Dockerfile"
  SOURCE="backend/"
else
  DOCKERFILE="mock-agent/Dockerfile"
  SOURCE="mock-agent/ (bootstrap: the real backend has no Dockerfile yet)"
fi

TAG="${TAG:-$(git rev-parse --short HEAD)$(git diff --quiet || echo '-dirty')}"

echo ">> Resolving the ECR repository from stack $FOUNDATION_STACK"
REPO_URI="$("${AWS[@]}" cloudformation describe-stacks --stack-name "$FOUNDATION_STACK" \
  --query "Stacks[0].Outputs[?OutputKey=='EcrRepositoryUri'].OutputValue" --output text)"
if [[ -z "$REPO_URI" || "$REPO_URI" == "None" ]]; then
  echo "!! Could not read EcrRepositoryUri from $FOUNDATION_STACK — is the foundation stack deployed?" >&2
  exit 1
fi
REGISTRY="${REPO_URI%%/*}"

echo ">> Building $DOCKERFILE  [source: $SOURCE]  tag: $TAG"
docker build -f "$DOCKERFILE" -t "$REPO_URI:$TAG" -t "$REPO_URI:latest" .

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
  --query 'taskDefinition' --output json > /tmp/sgs-td-current.json
python3 - "$REPO_URI:$TAG" <<'PY' > /tmp/sgs-td-next.json
import json, sys
image = sys.argv[1]
td = json.load(open('/tmp/sgs-td-current.json'))
for key in ('taskDefinitionArn', 'revision', 'status', 'requiresAttributes',
            'compatibilities', 'registeredAt', 'registeredBy', 'deregisteredAt'):
    td.pop(key, None)
for container in td['containerDefinitions']:
    container['image'] = image
json.dump(td, sys.stdout)
PY

NEW_TD_ARN="$("${AWS[@]}" ecs register-task-definition \
  --cli-input-json file:///tmp/sgs-td-next.json \
  --query 'taskDefinition.taskDefinitionArn' --output text)"
echo "   new:     $NEW_TD_ARN"

echo ">> Rolling the service"
"${AWS[@]}" ecs update-service --cluster "$CLUSTER" --service "$SERVICE" \
  --task-definition "$NEW_TD_ARN" --query 'service.deployments[0].[id,status]' --output text

echo ">> Waiting for the service to stabilise (circuit breaker rolls back on failure)"
if "${AWS[@]}" ecs wait services-stable --cluster "$CLUSTER" --services "$SERVICE"; then
  RUNNING_TD="$("${AWS[@]}" ecs describe-services --cluster "$CLUSTER" --services "$SERVICE" \
    --query 'services[0].taskDefinition' --output text)"
  echo ">> Done — running $RUNNING_TD"
  if [[ "$RUNNING_TD" != "$NEW_TD_ARN" ]]; then
    echo "!! The service rolled back to $RUNNING_TD — the new task never became healthy." >&2
    echo "   Check: aws logs tail /ecs/$SERVICE --since 15m ${PROFILE_ARGS[*]-} --region $REGION" >&2
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
    --task-definition $CURRENT_TD_ARN ${PROFILE_ARGS[*]-} --region $REGION

Note: infra/backend-service.yaml's ImageTag parameter is now stale by design
(CI owns the running image). If you ever update that stack, pass the tag that is
actually running so it does not revert: ImageTag=$TAG

This script only swaps the image; it never updates the service stack. To change a
template parameter (limits, ApiKey, McpServerUrl) use:

  PROFILE=$PROFILE ./scripts/deploy-backend-stack.sh McpServerUrl=...

That preserves every parameter you do not name - including this image tag. Do NOT use
a plain 'aws cloudformation deploy', which resolves anything you omit to its template
default and would empty SecondaryModelId, removing the fallback model. See
docs/deployment.md#backend-deployment.
EOF
