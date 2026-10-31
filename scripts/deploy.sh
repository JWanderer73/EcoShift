#!/usr/bin/env bash
# Local equivalent of the deploy workflow.
#   scripts/deploy.sh up            base -> build and push image -> training -> serving -> one pipeline run
#   scripts/deploy.sh down-serving  destroy the serving stack (the only part that costs real money per hour)
#   scripts/deploy.sh down-all      destroy serving, training and base (bootstrap is left alone)
#
# Needs: AWS credentials, Terraform, the AWS CLI, Docker (for `up`) and TF_STATE_BUCKET.
# AWS_REGION must be the region your AWS project allows (default us-east-2).
set -euo pipefail

cd "$(dirname "$0")/.."
action="${1:?usage: deploy.sh up|down-serving|down-all}"
: "${TF_STATE_BUCKET:?set TF_STATE_BUCKET to the Terraform state bucket name}"
export AWS_REGION="${AWS_REGION:-us-east-2}"
export TF_VAR_aws_region="$AWS_REGION" # every stack uses the same region

case "$action" in
  up)
    tag="$(date +%Y%m%d%H%M%S)" # unique each run so ECS always picks up the new image
    scripts/tf.sh base apply -auto-approve

    registry="$(aws sts get-caller-identity --query Account --output text).dkr.ecr.${AWS_REGION}.amazonaws.com"
    aws ecr get-login-password --region "$AWS_REGION" | docker login --username AWS --password-stdin "$registry"
    docker build --platform linux/amd64 -t "$registry/carbon-windows:$tag" -t "$registry/carbon-windows:latest" .
    docker push --all-tags "$registry/carbon-windows"

    scripts/tf.sh training apply -auto-approve -var "image_tag=$tag"
    scripts/tf.sh serving apply -auto-approve -var "image_tag=$tag"
    scripts/run_pipeline.sh
    echo "App is at $(scripts/tf.sh serving output -raw url)"
    ;;
  down-serving)
    scripts/tf.sh serving destroy -auto-approve
    ;;
  down-all)
    scripts/tf.sh serving destroy -auto-approve
    scripts/tf.sh training destroy -auto-approve
    scripts/tf.sh base destroy -auto-approve
    ;;
  *)
    echo "usage: deploy.sh up|down-serving|down-all" >&2
    exit 2
    ;;
esac
