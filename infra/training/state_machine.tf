locals {
  steps = ["ingest", "train", "gate", "predict"]

  next_state = {
    ingest  = "train"
    train   = "gate"
    gate    = "predict"
    predict = "Succeeded"
  }

  network = {
    AwsvpcConfiguration = {
      Subnets        = data.aws_subnets.default.ids
      SecurityGroups = [aws_security_group.jobs.id]
      AssignPublicIp = "ENABLED"
    }
  }

  # Every step is the same shape: run the task, wait for it, and on any error go to RecordFailure.
  # Only ingest is retried, because it is the step that calls external data sources.
  task_states = {
    for s in local.steps : s => {
      Type     = "Task"
      Resource = "arn:aws:states:::ecs:runTask.sync"
      Parameters = {
        Cluster              = data.aws_ecs_cluster.main.arn
        TaskDefinition       = aws_ecs_task_definition.jobs.arn
        LaunchType           = "FARGATE"
        NetworkConfiguration = local.network
        Overrides = {
          ContainerOverrides = [{
            Name    = "jobs"
            Command = ["python", "-m", "carbon.jobs.${s}"]
          }]
        }
      }
      Retry = [{
        ErrorEquals     = ["States.TaskFailed"]
        IntervalSeconds = 30
        MaxAttempts     = s == "ingest" ? 2 : 0
        BackoffRate     = 2.0
      }]
      Catch = [{
        ErrorEquals = ["States.ALL"]
        ResultPath  = "$.error"
        Next        = "RecordFailure"
      }]
      Next = local.next_state[s]
    }
  }

  failure_states = {
    # Write the failure into the status record the API reads. last_success_at is left alone,
    # so the API still knows how old the last good forecast is.
    RecordFailure = {
      Type     = "Task"
      Resource = "arn:aws:states:::dynamodb:updateItem"
      Parameters = {
        TableName        = local.status_table
        Key              = { pk = { S = "pipeline" } }
        UpdateExpression = "SET last_run_status = :s, last_error = :e, updated_at = :t"
        ExpressionAttributeValues = {
          ":s" = { S = "failed" }
          ":e" = { "S.$" = "States.JsonToString($.error)" }
          ":t" = { "S.$" = "$$.State.EnteredTime" }
        }
      }
      ResultPath = "$.recorded"
      Next       = "NotifyFailure"
    }
    NotifyFailure = {
      Type     = "Task"
      Resource = "arn:aws:states:::sns:publish"
      Parameters = {
        TopicArn    = data.aws_sns_topic.alerts.arn
        Subject     = "Carbon pipeline failed"
        "Message.$" = "States.JsonToString($.error)"
      }
      Next = "Failed"
    }
    Failed = {
      Type  = "Fail"
      Error = "PipelineFailed"
      Cause = "A pipeline step failed. See the status record and the task logs."
    }
    Succeeded = {
      Type = "Succeed"
    }
  }
}

resource "aws_sfn_state_machine" "pipeline" {
  name     = "${var.project}-pipeline"
  role_arn = aws_iam_role.sfn.arn

  definition = jsonencode({
    Comment = "ingest -> train -> gate -> predict, each as an ECS Fargate task"
    StartAt = "ingest"
    States  = merge(local.task_states, local.failure_states)
  })
}

data "aws_iam_policy_document" "sfn_assume" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["states.amazonaws.com"]
    }
  }
}

data "aws_iam_policy_document" "sfn" {
  statement {
    actions   = ["ecs:RunTask", "ecs:StopTask", "ecs:DescribeTasks"]
    resources = ["*"]
  }

  statement {
    actions   = ["iam:PassRole"]
    resources = [data.aws_iam_role.task_execution.arn, data.aws_iam_role.task.arn]
  }

  # Lets the .sync integration wait for the task to finish.
  statement {
    actions   = ["events:PutTargets", "events:PutRule", "events:DescribeRule"]
    resources = ["arn:aws:events:${var.aws_region}:${data.aws_caller_identity.current.account_id}:rule/StepFunctionsGetEventsForECSTaskRule"]
  }

  statement {
    actions   = ["dynamodb:UpdateItem"]
    resources = ["arn:aws:dynamodb:${var.aws_region}:${data.aws_caller_identity.current.account_id}:table/${local.status_table}"]
  }

  statement {
    actions   = ["sns:Publish"]
    resources = [data.aws_sns_topic.alerts.arn]
  }
}

resource "aws_iam_role" "sfn" {
  name               = "${var.project}-pipeline-sfn"
  assume_role_policy = data.aws_iam_policy_document.sfn_assume.json
}

resource "aws_iam_role_policy" "sfn" {
  name   = "pipeline"
  role   = aws_iam_role.sfn.id
  policy = data.aws_iam_policy_document.sfn.json
}
