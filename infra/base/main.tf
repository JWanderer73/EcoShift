# Cheap, long-lived resources. The serving and training stacks look these up by name,
# so apply this stack first and destroy it last.

data "aws_caller_identity" "current" {}

locals {
  bucket_name = "${var.project}-artifacts-${data.aws_caller_identity.current.account_id}"
}

resource "aws_ecr_repository" "app" {
  name                 = var.project
  image_tag_mutability = "MUTABLE"
  force_delete         = true
}

resource "aws_ecr_lifecycle_policy" "app" {
  repository = aws_ecr_repository.app.name

  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep the 10 most recent images"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 10
      }
      action = { type = "expire" }
    }]
  })
}

# Clean tables, the model registry (versioned models + champion pointer) and the forecast archive.
resource "aws_s3_bucket" "artifacts" {
  bucket        = local.bucket_name
  force_destroy = true
}

resource "aws_s3_bucket_versioning" "artifacts" {
  bucket = aws_s3_bucket.artifacts.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_public_access_block" "artifacts" {
  bucket                  = aws_s3_bucket.artifacts.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Items are keyed by location and "<model version>#<hour>".
resource "aws_dynamodb_table" "forecasts" {
  name         = "${var.project}-forecasts"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "location"
  range_key    = "sk"

  attribute {
    name = "location"
    type = "S"
  }

  attribute {
    name = "sk"
    type = "S"
  }
}

# One item (pk = "pipeline") holding last success, last run status and the served model versions.
resource "aws_dynamodb_table" "status" {
  name         = "${var.project}-status"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "pk"

  attribute {
    name = "pk"
    type = "S"
  }
}

resource "aws_sns_topic" "alerts" {
  name = "${var.project}-alerts"
}

resource "aws_sns_topic_subscription" "email" {
  count     = var.alert_email == "" ? 0 : 1
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email
}

resource "aws_cloudwatch_log_group" "ecs" {
  name              = "/ecs/${var.project}"
  retention_in_days = 7
}

resource "aws_ecs_cluster" "main" {
  name = var.project
}
