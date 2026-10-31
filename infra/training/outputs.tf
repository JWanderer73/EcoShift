output "state_machine_arn" {
  description = "Start a run by hand: aws stepfunctions start-execution --state-machine-arn <this>"
  value       = aws_sfn_state_machine.pipeline.arn
}
