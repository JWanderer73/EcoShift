variable "project" {
  type    = string
  default = "carbon-windows"
}

variable "aws_region" {
  description = "Must be the region your AWS project allows (AWS blocks workloads everywhere else)."
  type        = string
  default     = "us-east-2"
}

variable "state_bucket_name" {
  description = "Globally unique name for the Terraform state bucket."
  type        = string
}

variable "enable_github_oidc" {
  description = "Create the GitHub OIDC provider and deploy role. Leave false on the Free plan: its managed policy denies IAM identity-provider actions."
  type        = bool
  default     = false
}

variable "github_repo" {
  description = "Repository identity in the GitHub OIDC subject. Use OWNER@OWNER_ID/REPO@REPO_ID for immutable subjects or OWNER/REPO for legacy subjects."
  type        = string
  default     = ""
}

variable "create_oidc_provider" {
  description = "Set to false if the account already has the GitHub OIDC provider."
  type        = bool
  default     = true
}
