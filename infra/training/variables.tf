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
  description = "Comma-separated campus ids. Empty means every campus in the price model."
  type        = string
  default     = ""
}

variable "job_cpu" {
  type    = number
  default = 1024
}

variable "job_memory" {
  type    = number
  default = 4096
}

variable "schedules_enabled" {
  description = "Run the pipeline and accuracy job on a schedule. Leave false except while demoing."
  type        = bool
  default     = false
}

variable "biweekly_refresh_enabled" {
  description = "Enable a 14-day forecast refresh schedule when regular schedules are disabled."
  type        = bool
  default     = false
}

variable "pipeline_schedule" {
  description = "Refresh cadence. Also settable from config; CAISO day-ahead prices are published once a day."
  type        = string
  default     = "rate(1 day)"
}

variable "mae_alarm_threshold" {
  description = "Rolling MAE above this raises an alert and starts an extra retrain."
  type        = number
  default     = 15
}

variable "default_location" {
  description = "Location the accuracy alarm watches (the price model publishes one fleet-wide series, Location=all)."
  type        = string
  default     = "all"
}

variable "fail_step" {
  description = "Demo only: name of a step (ingest, train, gate, predict) that should crash on purpose."
  type        = string
  default     = ""
}

variable "model" {
  description = "price_xgb = the delivered CAISO day-ahead price model; stub = synthetic demo models."
  type        = string
  default     = "price_xgb"
}
