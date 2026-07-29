#!/usr/bin/env bash
#
# Read what the agent backend stored: user feedback and conversation turns.
# Read-only by construction — it only ever calls Query/Scan/DescribeTable, and
# the `sgs-llm-dev` role it is meant to be used with has no write permissions.
#
#   PROFILE=sgs-llm-dev ./scripts/read-db.sh feedback
#   PROFILE=sgs-llm-dev ./scripts/read-db.sh feedback --day 2026-07-29
#   PROFILE=sgs-llm-dev ./scripts/read-db.sh conversations --conversation <id>
#   PROFILE=sgs-llm-dev ./scripts/read-db.sh counts
#
# Output is JSONL (one record per line) with DynamoDB's type wrappers removed, so
# it pipes straight into jq, grep or a file. See
# docs/deployment.md#inspect-what-the-backend-stored.
set -euo pipefail

PROFILE="${PROFILE-swisstopo}"
REGION="${REGION:-eu-central-1}"
FEEDBACK_TABLE="${FEEDBACK_TABLE:-sgs-llm-feedback}"
CONVERSATION_TABLE="${CONVERSATION_TABLE:-sgs-llm-conversations}"
DAYS="${DAYS:-7}"
LIMIT="${LIMIT:-100}"

PROFILE_ARGS=()
if [[ -n "$PROFILE" ]]; then
  PROFILE_ARGS=(--profile "$PROFILE")
fi
AWS=(aws "${PROFILE_ARGS[@]}" --region "$REGION")

usage() {
  cat <<EOF
Usage: $(basename "$0") <feedback|conversations|counts> [options]

  feedback                     newest-first feedback from the last $DAYS days
  conversations                newest-first conversation turns from the last $DAYS days
  counts                       approximate item count per table

Options:
  --day YYYY-MM-DD             one specific day instead of the last $DAYS
  --days N                     how many days back to read (default $DAYS)
  --conversation ID            all turns of one conversation, in order
  --limit N                    max records per day (default $LIMIT)

Environment: PROFILE (default swisstopo), REGION (default $REGION)
EOF
}

# DynamoDB returns {"S":"x"} / {"N":"1"} wrappers; flatten them to plain JSON so
# the output is greppable and jq-able.
unwrap() {
  python3 -c '
import json, sys

def plain(value):
    (kind, inner), = value.items()
    if kind == "S": return inner
    if kind == "N": return float(inner) if "." in inner else int(inner)
    if kind == "BOOL": return inner
    if kind == "NULL": return None
    if kind == "L": return [plain(v) for v in inner]
    if kind == "M": return {k: plain(v) for k, v in inner.items()}
    if kind in ("SS", "NS", "BS"): return inner
    return inner

payload = json.load(sys.stdin)
for item in payload.get("Items", []):
    print(json.dumps({k: plain(v) for k, v in item.items()}, ensure_ascii=False))
'
}

query_by_day() {
  local table="$1" day="$2"
  "${AWS[@]}" dynamodb query \
    --table-name "$table" \
    --index-name ByDay \
    --key-condition-expression 'log_date = :d' \
    --expression-attribute-values "{\":d\":{\"S\":\"$day\"}}" \
    --no-scan-index-forward \
    --limit "$LIMIT" \
    --output json | unwrap
}

recent_days() {
  local n="$1"
  python3 -c '
import datetime, sys
n = int(sys.argv[1])
today = datetime.datetime.now(datetime.timezone.utc).date()
for offset in range(n):
    print(today - datetime.timedelta(days=offset))
' "$n"
}

COMMAND="${1:-}"
shift || true

DAY=""
CONVERSATION=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --day) DAY="$2"; shift 2 ;;
    --days) DAYS="$2"; shift 2 ;;
    --conversation) CONVERSATION="$2"; shift 2 ;;
    --limit) LIMIT="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "!! Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

case "$COMMAND" in
  feedback)
    if [[ -n "$DAY" ]]; then
      query_by_day "$FEEDBACK_TABLE" "$DAY"
    else
      while read -r day; do query_by_day "$FEEDBACK_TABLE" "$day"; done < <(recent_days "$DAYS")
    fi
    ;;
  conversations)
    if [[ -n "$CONVERSATION" ]]; then
      # One conversation reads back in order: `turn` sorts as "<ts>#<message_id>".
      "${AWS[@]}" dynamodb query \
        --table-name "$CONVERSATION_TABLE" \
        --key-condition-expression 'conversation_id = :c' \
        --expression-attribute-values "{\":c\":{\"S\":\"$CONVERSATION\"}}" \
        --output json | unwrap
    elif [[ -n "$DAY" ]]; then
      query_by_day "$CONVERSATION_TABLE" "$DAY"
    else
      while read -r day; do query_by_day "$CONVERSATION_TABLE" "$day"; done < <(recent_days "$DAYS")
    fi
    ;;
  counts)
    # ItemCount is updated roughly every six hours, so treat it as approximate.
    for table in "$FEEDBACK_TABLE" "$CONVERSATION_TABLE"; do
      count="$("${AWS[@]}" dynamodb describe-table --table-name "$table" \
        --query 'Table.ItemCount' --output text)"
      echo "$table: ~$count items"
    done
    ;;
  ''|-h|--help)
    usage
    [[ -z "$COMMAND" ]] && exit 2 || exit 0
    ;;
  *)
    echo "!! Unknown command: $COMMAND" >&2
    usage >&2
    exit 2
    ;;
esac
