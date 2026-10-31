#!/usr/bin/env bash
# Start one pipeline run in AWS and wait for it to finish. Exits non-zero if the run fails.
set -euo pipefail

arn="$("$(dirname "$0")/tf.sh" training output -raw state_machine_arn)"
execution="$(aws stepfunctions start-execution --state-machine-arn "$arn" --query executionArn --output text)"
echo "started ${execution}"

status="RUNNING"
for _ in $(seq 1 60); do
  status="$(aws stepfunctions describe-execution --execution-arn "$execution" --query status --output text)"
  [ "$status" != "RUNNING" ] && break
  sleep 15
done
echo "status: ${status}"
[ "$status" = "SUCCEEDED" ]
