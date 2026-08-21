#!/usr/bin/env bash
#
# Idempotently expose the backend's mounted /mcp application through the existing
# CloudFront distribution. The new behavior clones /feedback's proven ALB, no-cache,
# all-viewer-header and all-method configuration; only the path changes.
#
#   PROFILE=swisstopo ./scripts/configure-exploration-mcp-route.sh
#   PROFILE=swisstopo ACTION=remove ./scripts/configure-exploration-mcp-route.sh
#   PROFILE=swisstopo DRY_RUN=1 ./scripts/configure-exploration-mcp-route.sh
set -euo pipefail

PROFILE="${PROFILE-swisstopo}"
REGION="${REGION:-us-east-1}"
DISTRIBUTION_ID="${DISTRIBUTION_ID:-E2AEIO5QX64WCY}"
MCP_PATH="${MCP_PATH:-/mcp}"
SOURCE_PATH="${SOURCE_PATH:-/feedback}"
ACTION="${ACTION:-ensure}"
DRY_RUN="${DRY_RUN:-0}"

if [[ "$ACTION" != "ensure" && "$ACTION" != "remove" ]]; then
  echo "ACTION must be 'ensure' or 'remove'." >&2
  exit 2
fi
if ! command -v jq >/dev/null 2>&1; then
  echo "jq is required." >&2
  exit 2
fi

PROFILE_ARGS=()
if [[ -n "$PROFILE" ]]; then
  PROFILE_ARGS=(--profile "$PROFILE")
fi
AWS=(aws ${PROFILE_ARGS[@]+"${PROFILE_ARGS[@]}"} --region "$REGION")

WORK_DIR="$(mktemp -d "${TMPDIR:-/tmp}/sgs-mcp-route.XXXXXX")"
trap 'rm -rf "$WORK_DIR"' EXIT
CURRENT="$WORK_DIR/current.json"
NEXT="$WORK_DIR/next.json"

echo ">> Reading CloudFront distribution $DISTRIBUTION_ID"
"${AWS[@]}" cloudfront get-distribution-config --id "$DISTRIBUTION_ID" > "$CURRENT"
ETAG="$(jq -r '.ETag' "$CURRENT")"

if [[ "$ACTION" == "ensure" ]]; then
  SOURCE_COUNT="$(jq --arg source "$SOURCE_PATH" \
    '[.DistributionConfig.CacheBehaviors.Items[] | select(.PathPattern == $source)] | length' \
    "$CURRENT")"
  if [[ "$SOURCE_COUNT" != "1" ]]; then
    echo "Expected exactly one $SOURCE_PATH behavior to clone; found $SOURCE_COUNT." >&2
    exit 1
  fi
  jq --arg source "$SOURCE_PATH" --arg path "$MCP_PATH" '
    .DistributionConfig
    | (.CacheBehaviors.Items // []) as $items
    | ($items | map(select(.PathPattern == $source)) | first) as $template
    | .CacheBehaviors.Items = (
        ($items | map(select(.PathPattern != $path)))
        + [($template | .PathPattern = $path)]
      )
    | .CacheBehaviors.Quantity = (.CacheBehaviors.Items | length)
  ' "$CURRENT" > "$NEXT"
else
  jq --arg path "$MCP_PATH" '
    .DistributionConfig
    | .CacheBehaviors.Items = (
        (.CacheBehaviors.Items // []) | map(select(.PathPattern != $path))
      )
    | .CacheBehaviors.Quantity = (.CacheBehaviors.Items | length)
  ' "$CURRENT" > "$NEXT"
fi

if [[ "$DRY_RUN" == "1" ]]; then
  jq --arg path "$MCP_PATH" '
    .CacheBehaviors.Items[] | select(.PathPattern == $path)
    | {PathPattern, TargetOriginId, AllowedMethods, CachePolicyId, OriginRequestPolicyId}
  ' "$NEXT"
  echo ">> DRY_RUN=1 — distribution not changed"
  exit 0
fi

echo ">> Applying $ACTION for $MCP_PATH"
"${AWS[@]}" cloudfront update-distribution \
  --id "$DISTRIBUTION_ID" \
  --if-match "$ETAG" \
  --distribution-config "file://$NEXT" \
  --query 'Distribution.[Id,Status]' \
  --output text
"${AWS[@]}" cloudfront wait distribution-deployed --id "$DISTRIBUTION_ID"

DOMAIN="$("${AWS[@]}" cloudfront get-distribution \
  --id "$DISTRIBUTION_ID" --query 'Distribution.DomainName' --output text)"
if [[ "$ACTION" == "ensure" ]]; then
  echo ">> Public MCP: https://$DOMAIN$MCP_PATH"
else
  echo ">> Removed $MCP_PATH from https://$DOMAIN"
fi
