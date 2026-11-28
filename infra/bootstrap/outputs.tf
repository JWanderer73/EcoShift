output "state_bucket" {
  description = "Set this as TF_STATE_BUCKET."
  value       = aws_s3_bucket.state.id
}

output "github_actions_role_arn" {
  description = "Set this as the AWS_ROLE_ARN repository variable (null unless enable_github_oidc)."
  value       = try(aws_iam_role.github[0].arn, null)
}
