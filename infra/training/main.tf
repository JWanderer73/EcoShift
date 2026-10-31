# Training path: EventBridge -> Step Functions -> four ECS Fargate tasks
# (ingest, train, gate, predict) from the same container image.
# Apply the base stack first and push an image to ECR before applying this one.

data "aws_caller_identity" "current" {}

data "aws_vpc" "default" {
  default = true
}

data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }

  filter {
    name   = "default-for-az"
    values = ["true"]
  }
}

data "aws_ecr_repository" "app" {
  name = var.project
}

data "aws_ecs_cluster" "main" {
  cluster_name = var.project
}

data "aws_iam_role" "task_execution" {
  name = "${var.project}-task-execution"
}

data "aws_iam_role" "task" {
  name = "${var.project}-task"
}

data "aws_cloudwatch_log_group" "ecs" {
  name = "/ecs/${var.project}"
}

data "aws_sns_topic" "alerts" {
  name = "${var.project}-alerts"
}

locals {
  status_table = "${var.project}-status"
}

# Outbound only: tasks pull data from the internet and talk to AWS APIs. No NAT, so public IPs.
resource "aws_security_group" "jobs" {
  name        = "${var.project}-jobs"
  description = "Pipeline tasks, outbound only"
  vpc_id      = data.aws_vpc.default.id

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

# One task definition; each step overrides the command.
resource "aws_ecs_task_definition" "jobs" {
  family                   = "${var.project}-jobs"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.job_cpu
  memory                   = var.job_memory
  execution_role_arn       = data.aws_iam_role.task_execution.arn
  task_role_arn            = data.aws_iam_role.task.arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "X86_64"
  }

  container_definitions = jsonencode([{
    name      = "jobs"
    image     = "${data.aws_ecr_repository.app.repository_url}:${var.image_tag}"
    essential = true
    command   = ["python", "-m", "carbon.jobs.pipeline"]
    environment = [
      { name = "AWS_REGION", value = var.aws_region },
      { name = "CARBON_STORE", value = "aws" },
      { name = "CARBON_FORECASTS_TABLE", value = "${var.project}-forecasts" },
      { name = "CARBON_STATUS_TABLE", value = local.status_table },
      { name = "CARBON_ARTIFACTS_BUCKET", value = "${var.project}-artifacts-${data.aws_caller_identity.current.account_id}" },
      { name = "CARBON_LOCATIONS", value = var.locations },
      { name = "FAIL_STEP", value = var.fail_step },
    ]
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = data.aws_cloudwatch_log_group.ecs.name
        "awslogs-region"        = var.aws_region
        "awslogs-stream-prefix" = "jobs"
      }
    }
  }])
}
