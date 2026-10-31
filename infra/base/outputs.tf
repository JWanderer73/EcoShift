output "ecr_repository_url" {
  value = aws_ecr_repository.app.repository_url
}

output "artifacts_bucket" {
  value = aws_s3_bucket.artifacts.id
}

output "alerts_topic_arn" {
  value = aws_sns_topic.alerts.arn
}
