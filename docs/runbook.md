# Runbook

## Know your account's rules first

This project was written for an AWS account in AWS's newer "projects" experience. AWS manages the
account's policies there, and they matter:

- **One region only.** Workloads run only in the region you picked for the project. `us-east-1` and
  `us-west-2` are blocked for almost everything, so a default CLI region of `us-east-1` fails with
  "explicit deny in a service control policy". This repo defaults to `us-east-2`. If yours differs,
  find it with:

  ```zsh
  for r in $(aws ec2 describe-regions --region us-east-1 --query 'Regions[].RegionName' --output text); do
    if aws ec2 describe-vpcs --region $r --query 'Vpcs[0].VpcId' --output text >/dev/null 2>&1; then echo "allowed  $r"; else echo "denied   $r"; fi
  done
  ```

  then run `aws configure set region <that region>`, `export AWS_REGION=<that region>`, and pass
  `-var aws_region=<that region>` to any Terraform you run by hand.
- **No GitHub OIDC on the Free plan.** The managed policy denies IAM identity-provider actions, so
  the keyless GitHub Actions deploy cannot be set up. The default path below deploys from one
  person's machine. The workflows remain for accounts where OIDC works (see the end of this file).

Everything below is run from a terminal with AWS credentials for the account (for example the
`admin-cli` IAM user) and Terraform 1.10 or later. Avoid angle brackets in commands: zsh treats `<`
as a redirect, so substitute real values.

## 0. Check the account allows what we use (week 1, about an hour)

```zsh
aws configure set region us-east-2
cd infra/freeplan-check
terraform init
terraform apply -var aws_region=us-east-2   # ECS Fargate + an ALB with a public nginx image
# open the printed URL (give it a couple of minutes), then:
terraform destroy -var aws_region=us-east-2 # right away: the ALB bills by the hour
```

Also check the Fargate vCPU limit under Service Quotas (it can be as low as 6). Add up what runs at
once: 2 x 0.25 (API) + 0.5 (dashboard) + 0.5 (a job).

If this fails, the fallback is a Lambda-based design (no VPC) or the club's DS3 account.

## 1. One-time setup

1. One person owns the AWS account (Free plan, root MFA on). Never upgrade to the Paid plan.
2. Create the Terraform state bucket (local state; keep the `terraform.tfstate` file in `infra/bootstrap`):

   ```zsh
   cd infra/bootstrap
   terraform init
   terraform apply -var state_bucket_name=myclub-carbon-tfstate-8431
   ```

   Pick a globally unique name. Then, from the repo root:

   ```zsh
   export TF_STATE_BUCKET=myclub-carbon-tfstate-8431
   export AWS_REGION=us-east-2
   ```

Only one person should run the deploy script at a time (Terraform state locking protects against
overlapping runs, but coordinate anyway).

## 2. Bring the system up

```zsh
scripts/deploy.sh up
```

This applies the base stack, builds and pushes the image (needs Docker running), applies training
and serving, runs the pipeline once so there are forecasts, and prints the URL (plain HTTP).

- Dashboard: `http://ALB-ADDRESS/`
- API docs: `http://ALB-ADDRESS/docs`
- CLI: `export CARBON_API_URL=http://ALB-ADDRESS`, then `carbon-windows best -d 4 -w 1d`

The first deploys usually take a few tries because the Terraform has never been applied. Read the
error and fix it. Tasks that exit immediately are usually an image architecture mismatch (the
script builds for `linux/amd64`) or a missing log group; check CloudWatch Logs under `/ecs/carbon-windows`.

## 3. Resilience demo

Healthy: show the dashboard, `carbon-windows status`, and `curl http://ALB-ADDRESS/v1/health`.

**Pipeline fails.** Make a step crash, then run the pipeline:

```zsh
scripts/tf.sh training apply -auto-approve -var fail_step=train
scripts/run_pipeline.sh            # ends FAILED; Step Functions records the failure and alerts SNS
carbon-windows best -d 4 -w 1d     # still answers, exit code 4, warning: pipeline_failed
```

The dashboard shows a banner and the status record has the error. Fix it with `-var fail_step=` and
run the pipeline again.

**Pipeline stops running.** Nothing records a failure here, so the API notices the forecast aging:

```zsh
scripts/tf.sh serving apply -auto-approve -var stale_after_hours=0.05   # about 3 minutes
# wait a few minutes: warnings now include forecast_stale
scripts/tf.sh serving apply -auto-approve                                # back to 6 hours
```

**A task dies.** Stop one API task in the ECS console. The ALB health check routes around it and ECS
starts a replacement; requests keep succeeding.

## 4. Schedules

Pipeline and accuracy schedules are disabled by default (every run costs a little). Enable them for
a demo with:

```zsh
scripts/tf.sh training apply -auto-approve -var schedules_enabled=true
```

The refresh cadence is `pipeline_schedule` (default every 3 hours, a placeholder).

## 5. Tear down

- Whenever you stop working: `scripts/deploy.sh down-serving`. The ALB bills by the hour even with no
  tasks, so don't leave the serving stack up. There is no automatic nightly destroy on this path;
  make it a habit, or set a calendar reminder.
- After the demo: record a video and screenshots first, then `scripts/deploy.sh down-all`. Bootstrap
  (the state bucket) stays; delete it by hand if you want.
- Buckets and the ECR repo are set to force-delete, so destroy will not stall on non-empty ones.

## Optional: deploying from GitHub Actions

Only possible if the account allows IAM OIDC providers (not the Free plan in this account type).
If it does:

1. Apply bootstrap with `-var enable_github_oidc=true -var github_repo=OWNER/REPO` (use the real values).
2. In GitHub, Settings > Secrets and variables > Actions > Variables, set `AWS_ROLE_ARN` (the
   `github_actions_role_arn` output), `TF_STATE_BUCKET`, `AWS_REGION`, and `NIGHTLY_DESTROY=true`.
3. Run the **deploy** workflow with action `up`. The **nightly-destroy** workflow then removes the
   serving stack every night. Do not commit credentials: this repo is public.

An alternative is storing an IAM user's access keys as GitHub secrets and swapping the credentials
step in the workflows. That works but uses long-lived keys.

## Troubleshooting

| Symptom | Likely cause |
|---------|--------------|
| "explicit deny in a service control policy" | Wrong region. Use the project's region (see the top of this file). |
| `no matching EC2 VPC found` | The region has no default VPC. Try `aws ec2 create-default-vpc`, or change the Terraform to create a small VPC. |
| `AccessDenied` on `iam:CreateOpenIDConnectProvider` | OIDC is blocked on this account. Leave `enable_github_oidc` false. |
| API returns 503 `no_forecast` | The pipeline has not run yet. Run `scripts/run_pipeline.sh`. |
| Targets unhealthy in the ALB | Health check grace period, a crashing container (see logs), or the wrong image architecture. |
| Pipeline fails at `ingest` | Data source unreachable or validation rejected the batch (a gap longer than 3 hours). |
| `terraform destroy` stalls | Something outside Terraform is using the resources (a running task, files you added by hand). |
| Unexpected credit use | The ALB left running. Check with `scripts/tf.sh serving state list`. |
