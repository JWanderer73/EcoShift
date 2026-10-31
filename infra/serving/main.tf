# Serving path: ALB (two AZs) -> ECS Fargate API and dashboard services -> DynamoDB.
# This is the only expensive stack (the ALB bills hourly), so it is destroyed overnight.
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

locals {
  image = "${data.aws_ecr_repository.app.repository_url}:${var.image_tag}"

  app_env = [
    { name = "AWS_REGION", value = var.aws_region },
    { name = "CARBON_STORE", value = "aws" },
    { name = "CARBON_FORECASTS_TABLE", value = "${var.project}-forecasts" },
    { name = "CARBON_STATUS_TABLE", value = "${var.project}-status" },
    { name = "CARBON_ARTIFACTS_BUCKET", value = "${var.project}-artifacts-${data.aws_caller_identity.current.account_id}" },
    { name = "CARBON_LOCATIONS", value = var.locations },
    { name = "CARBON_STALE_AFTER_HOURS", value = tostring(var.stale_after_hours) },
  ]

  log_options = {
    "awslogs-group"  = data.aws_cloudwatch_log_group.ecs.name
    "awslogs-region" = var.aws_region
  }
}

# --- networking: no NAT gateway (it costs ~$33/month per AZ). Tasks get public IPs and
# --- only accept traffic from the load balancer.

resource "aws_security_group" "alb" {
  name        = "${var.project}-alb"
  description = "Public HTTP to the load balancer"
  vpc_id      = data.aws_vpc.default.id

  ingress {
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_security_group" "tasks" {
  name        = "${var.project}-serving-tasks"
  description = "Traffic from the load balancer only"
  vpc_id      = data.aws_vpc.default.id

  ingress {
    from_port       = 8000
    to_port         = 8000
    protocol        = "tcp"
    security_groups = [aws_security_group.alb.id]
  }

  ingress {
    from_port       = 8501
    to_port         = 8501
    protocol        = "tcp"
    security_groups = [aws_security_group.alb.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

# --- load balancer ---

resource "aws_lb" "main" {
  name               = var.project
  load_balancer_type = "application"
  subnets            = data.aws_subnets.default.ids
  security_groups    = [aws_security_group.alb.id]
}

resource "aws_lb_target_group" "api" {
  name                 = "${var.project}-api"
  port                 = 8000
  protocol             = "HTTP"
  target_type          = "ip"
  vpc_id               = data.aws_vpc.default.id
  deregistration_delay = 10

  health_check {
    path     = "/v1/health"
    matcher  = "200"
    interval = 15
  }
}

resource "aws_lb_target_group" "dashboard" {
  name                 = "${var.project}-dashboard"
  port                 = 8501
  protocol             = "HTTP"
  target_type          = "ip"
  vpc_id               = data.aws_vpc.default.id
  deregistration_delay = 10

  health_check {
    path     = "/_stcore/health"
    matcher  = "200"
    interval = 15
  }
}

resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.main.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.dashboard.arn
  }
}

resource "aws_lb_listener_rule" "api" {
  listener_arn = aws_lb_listener.http.arn
  priority     = 10

  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.api.arn
  }

  condition {
    path_pattern {
      values = ["/v1/*", "/docs", "/openapi.json"]
    }
  }
}

# --- API service: two fixed tasks, spread across AZs by the subnets below ---

resource "aws_ecs_task_definition" "api" {
  family                   = "${var.project}-api"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.api_cpu
  memory                   = var.api_memory
  execution_role_arn       = data.aws_iam_role.task_execution.arn
  task_role_arn            = data.aws_iam_role.task.arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "X86_64"
  }

  container_definitions = jsonencode([{
    name         = "api"
    image        = local.image
    essential    = true
    command      = ["uvicorn", "carbon.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
    portMappings = [{ containerPort = 8000, protocol = "tcp" }]
    environment  = local.app_env
    logConfiguration = {
      logDriver = "awslogs"
      options   = merge(local.log_options, { "awslogs-stream-prefix" = "api" })
    }
  }])
}

resource "aws_ecs_service" "api" {
  name                              = "api"
  cluster                           = data.aws_ecs_cluster.main.arn
  task_definition                   = aws_ecs_task_definition.api.arn
  desired_count                     = var.api_desired_count
  launch_type                       = "FARGATE"
  health_check_grace_period_seconds = 60

  network_configuration {
    subnets          = data.aws_subnets.default.ids
    security_groups  = [aws_security_group.tasks.id]
    assign_public_ip = true
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.api.arn
    container_name   = "api"
    container_port   = 8000
  }

  depends_on = [aws_lb_listener.http]
}

# --- dashboard service ---

resource "aws_ecs_task_definition" "dashboard" {
  family                   = "${var.project}-dashboard"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.dashboard_cpu
  memory                   = var.dashboard_memory
  execution_role_arn       = data.aws_iam_role.task_execution.arn
  task_role_arn            = data.aws_iam_role.task.arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "X86_64"
  }

  container_definitions = jsonencode([{
    name      = "dashboard"
    image     = local.image
    essential = true
    command = [
      "streamlit", "run", "dashboard/app.py",
      "--server.port=8501", "--server.address=0.0.0.0", "--server.headless=true",
    ]
    portMappings = [{ containerPort = 8501, protocol = "tcp" }]
    environment = [
      { name = "API_URL", value = "http://${aws_lb.main.dns_name}" },
      { name = "DEFAULT_LOCATION", value = split(",", var.locations)[0] },
    ]
    logConfiguration = {
      logDriver = "awslogs"
      options   = merge(local.log_options, { "awslogs-stream-prefix" = "dashboard" })
    }
  }])
}

resource "aws_ecs_service" "dashboard" {
  name                              = "dashboard"
  cluster                           = data.aws_ecs_cluster.main.arn
  task_definition                   = aws_ecs_task_definition.dashboard.arn
  desired_count                     = var.dashboard_desired_count
  launch_type                       = "FARGATE"
  health_check_grace_period_seconds = 60

  network_configuration {
    subnets          = data.aws_subnets.default.ids
    security_groups  = [aws_security_group.tasks.id]
    assign_public_ip = true
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.dashboard.arn
    container_name   = "dashboard"
    container_port   = 8501
  }

  depends_on = [aws_lb_listener.http]
}
