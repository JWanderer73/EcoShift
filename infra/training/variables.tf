variable "project" {
  type    = string
  default = "carbon-windows"
}

variable "aws_region" {
  type    = string
  default = "us-east-2"
}

variable "image_tag" {
  type    = string
  default = "latest"
}

variable "locations" {
  description = "Comma-separated location ids the pipeline processes."
  type        = string
  default     = "demo-region"
}

variable "job_cpu" {
  type    = number
  default = 512
}

variable "job_memory" {
  type    = number
  default = 1024
}

variable "schedules_enabled" {
  description = "Run the pipeline and accuracy job on a schedule. Leave false except while demoing."
  type        = bool
  default     = false
}

variable "pipeline_schedule" {
  description = "Refresh cadence. Also settable from config; 3 hours is a placeholder."
  type        = string
  default     = "rate(3 hours)"
}

variable "mae_alarm_threshold" {
  description = "Rolling MAE above this raises an alert and starts an extra retrain."
  type        = number
  default     = 40
}

variable "default_location" {
  description = "Location the accuracy alarm watches."
  type        = string
  default     = "demo-region"
}

variable "fail_step" {
  description = "Demo only: name of a step (ingest, train, gate, predict) that should crash on purpose."
  type        = string
  default     = ""
}
