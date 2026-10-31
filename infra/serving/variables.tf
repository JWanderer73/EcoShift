variable "project" {
  type    = string
  default = "carbon-windows"
}

variable "aws_region" {
  type    = string
  default = "us-east-2"
}

variable "image_tag" {
  description = "Tag of the container image in ECR."
  type        = string
  default     = "latest"
}

variable "api_desired_count" {
  description = "API tasks. Two fixed tasks spread across two AZs."
  type        = number
  default     = 2
}

variable "dashboard_desired_count" {
  type    = number
  default = 1
}

variable "api_cpu" {
  type    = number
  default = 256
}

variable "api_memory" {
  type    = number
  default = 512
}

variable "dashboard_cpu" {
  type    = number
  default = 512
}

variable "dashboard_memory" {
  type    = number
  default = 1024
}

variable "locations" {
  description = "Comma-separated location ids the API serves."
  type        = string
  default     = "demo-region"
}

variable "stale_after_hours" {
  description = "Forecasts older than this get a forecast_stale warning. Lower it to demo staleness."
  type        = number
  default     = 6
}
