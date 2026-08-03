#!/usr/bin/env bash
#
# Update the backend service stack while PRESERVING every parameter you are not
# changing. See docs/deployment.md#backend-deployment.
#
#   PROFILE=swisstopo ./scripts/deploy-backend-stack.sh McpServerUrl=https://mcp.example.ch/mcp
#   DRY_RUN=1 ./scripts/deploy-backend-stack.sh ApiKey=...      # show the plan only
#
# Why this exists rather than a plain `aws cloudformation deploy`: that command resolves
# every parameter absent from --parameter-overrides to its TEMPLATE DEFAULT, not to the
# value currently deployed. SecondaryModelId defaults to empty, so one forgotten override
# silently removes the fallback model - and while the SCP blocks Claude that leaves every
# turn failing. This script sends UsePreviousValue for everything it is not asked to
# change, so that class of mistake is impossible. It also handles NoEcho parameters
# (ApiKey), whose real values cannot be read back and re-sent.
#
# ImageTag is preserved the same way, which matters because CI owns the running image and
# the template's value is stale by design.
set -euo pipefail

PROFILE="${PROFILE-swisstopo}"
REGION="${REGION:-eu-central-1}"
STACK="${STACK:-sgs-llm-backend-service}"
DRY_RUN="${DRY_RUN:-0}"

if [[ $# -eq 0 ]]; then
  echo "usage: $0 Key=Value [Key=Value ...]" >&2
  echo "       nothing to change means nothing to do; pass at least one parameter." >&2
  exit 2
fi

PROFILE_ARGS=()
if [[ -n "$PROFILE" ]]; then
  PROFILE_ARGS=(--profile "$PROFILE")
fi
AWS=(aws "${PROFILE_ARGS[@]}" --region "$REGION")

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TEMPLATE="$ROOT/infra/backend-service.yaml"

echo ">> Reading the parameters currently deployed on $STACK"
CURRENT="$("${AWS[@]}" cloudformation describe-stacks --stack-name "$STACK" \
  --query 'Stacks[0].Parameters' --output json)"
if [[ -z "$CURRENT" || "$CURRENT" == "None" || "$CURRENT" == "null" ]]; then
  echo "!! Could not read the deployed parameters of $STACK - is it deployed?" >&2
  exit 1
fi

# Build the --parameters list: an explicit value for each override, UsePreviousValue for
# every other parameter the stack already has. A template parameter that the deployed
# stack does not yet have (a newly added one) is omitted so its template default applies -
# UsePreviousValue would fail for it.
#
# Command substitution, not `< <(...)`: a failure inside a process substitution does not
# propagate under `set -e`. PARAMS would be empty and the update would reset every
# parameter to its template default.
if ! RESOLVED="$(python3 - "$CURRENT" "$@" <<'PY'
import json, sys

current = {p["ParameterKey"] for p in json.loads(sys.argv[1])}
overrides = {}
for pair in sys.argv[2:]:
    if "=" not in pair:
        sys.exit(f"not a Key=Value pair: {pair}")
    key, value = pair.split("=", 1)
    if "," in value:
        # ParameterKey=K,ParameterValue=V is comma-delimited shorthand, so a comma in the
        # value splits into a bogus second field.
        sys.exit(f"{key} value contains a comma, which this shorthand cannot express: {value}")
    overrides[key] = value

for key, value in overrides.items():
    print(f"ParameterKey={key},ParameterValue={value}")
for key in sorted(current - set(overrides)):
    print(f"ParameterKey={key},UsePreviousValue=true")
PY
)"; then
  echo "!! Could not resolve the parameter list; nothing submitted." >&2
  exit 1
fi

mapfile -t PARAMS <<<"$RESOLVED"
if [[ ${#PARAMS[@]} -eq 0 || -z "${PARAMS[0]}" ]]; then
  echo "!! Resolved an empty parameter list; refusing to submit." >&2
  exit 1
fi

echo ">> Resolved parameters:"
for entry in "${PARAMS[@]}"; do
  # Do not echo a NoEcho value that was passed on the command line.
  case "$entry" in
    ParameterKey=ApiKey,ParameterValue=*) echo "   ParameterKey=ApiKey,ParameterValue=<hidden>" ;;
    *) echo "   $entry" ;;
  esac
done

if [[ "$DRY_RUN" == "1" ]]; then
  echo ">> DRY_RUN=1 - nothing submitted"
  exit 0
fi

echo ">> Updating $STACK"
"${AWS[@]}" cloudformation update-stack \
  --stack-name "$STACK" \
  --template-body "file://$TEMPLATE" \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameters "${PARAMS[@]}" \
  --query 'StackId' --output text

echo ">> Waiting for the update to complete"
if "${AWS[@]}" cloudformation wait stack-update-complete --stack-name "$STACK"; then
  echo ">> Done"
else
  echo "!! Update failed or rolled back. Inspect:" >&2
  echo "   aws cloudformation describe-stack-events --stack-name $STACK ${PROFILE_ARGS[*]} --region $REGION --max-items 20" >&2
  exit 1
fi
