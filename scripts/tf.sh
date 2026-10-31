#!/usr/bin/env bash
# Run Terraform for one stack with the shared remote state backend.
#   scripts/tf.sh base apply -auto-approve
#   scripts/tf.sh serving destroy -auto-approve
# Needs AWS credentials and TF_STATE_BUCKET (the bucket the bootstrap stack created).
set -euo pipefail

stack="${1:?usage: tf.sh <base|serving|training> <terraform args...>}"
shift
: "${TF_STATE_BUCKET:?set TF_STATE_BUCKET to the Terraform state bucket name}"

cd "$(dirname "$0")/../infra/${stack}"
terraform init -input=false -reconfigure \
  -backend-config="bucket=${TF_STATE_BUCKET}" \
  -backend-config="region=${AWS_REGION:-us-east-2}" >/dev/null
terraform "$@"
