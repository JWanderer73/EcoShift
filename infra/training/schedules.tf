# Schedules are disabled unless var.schedules_enabled is true, because every run costs a little.

data "aws_iam_policy_document" "events_assume" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["events.amazonaws.com"]
    }
  }
}

data "aws_iam_policy_document" "events" {
  statement {
    actions   = ["states:StartExecution"]
    resources = [aws_sfn_state_machine.pipeline.arn]
  }

  statement {
    actions   = ["ecs:RunTask"]
    resources = ["*"]
  }

  statement {
    actions   = ["iam:PassRole"]
    resources = [data.aws_iam_role.task_execution.arn, data.aws_iam_role.task.arn]
  }
}

resource "aws_iam_role" "events" {
  name               = "${var.project}-events"
  assume_role_policy = data.aws_iam_policy_document.events_assume.json
}

resource "aws_iam_role_policy" "events" {
  name   = "start-pipeline-and-accuracy"
  role   = aws_iam_role.events.id
  policy = data.aws_iam_policy_document.events.json
}

# Refresh forecasts (the whole pipeline).
resource "aws_cloudwatch_event_rule" "pipeline" {
  name                = "${var.project}-pipeline"
  schedule_expression = var.pipeline_schedule
  state               = var.schedules_enabled ? "ENABLED" : "DISABLED"
}

resource "aws_cloudwatch_event_target" "pipeline" {
  rule     = aws_cloudwatch_event_rule.pipeline.name
  arn      = aws_sfn_state_machine.pipeline.arn
  role_arn = aws_iam_role.events.arn
}

# Score past forecasts against actuals every hour.
resource "aws_cloudwatch_event_rule" "accuracy" {
  name                = "${var.project}-accuracy"
  schedule_expression = "rate(1 hour)"
  state               = var.schedules_enabled ? "ENABLED" : "DISABLED"
}

resource "aws_cloudwatch_event_target" "accuracy" {
  rule     = aws_cloudwatch_event_rule.accuracy.name
  arn      = data.aws_ecs_cluster.main.arn
  role_arn = aws_iam_role.events.arn

  ecs_target {
    task_definition_arn = aws_ecs_task_definition.jobs.arn
    launch_type         = "FARGATE"
    task_count          = 1

    network_configuration {
      subnets          = data.aws_subnets.default.ids
      security_groups  = [aws_security_group.jobs.id]
      assign_public_ip = true
    }
  }

  input = jsonencode({
    containerOverrides = [{
      name    = "jobs"
      command = ["python", "-m", "carbon.jobs.accuracy"]
    }]
  })
}

# Rolling error too high: alert, and start an extra retrain.
resource "aws_cloudwatch_metric_alarm" "mae" {
  alarm_name          = "${var.project}-rolling-mae-high"
  namespace           = "Carbon"
  metric_name         = "RollingMAE"
  dimensions          = { Location = var.default_location }
  statistic           = "Average"
  period              = 3600
  evaluation_periods  = 1
  threshold           = var.mae_alarm_threshold
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [data.aws_sns_topic.alerts.arn]
}

resource "aws_cloudwatch_event_rule" "retrain_on_alarm" {
  name = "${var.project}-retrain-on-alarm"

  event_pattern = jsonencode({
    source      = ["aws.cloudwatch"]
    detail-type = ["CloudWatch Alarm State Change"]
    detail = {
      alarmName = [aws_cloudwatch_metric_alarm.mae.alarm_name]
      state     = { value = ["ALARM"] }
    }
  })
}

resource "aws_cloudwatch_event_target" "retrain_on_alarm" {
  rule     = aws_cloudwatch_event_rule.retrain_on_alarm.name
  arn      = aws_sfn_state_machine.pipeline.arn
  role_arn = aws_iam_role.events.arn
}
