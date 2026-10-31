# Applied once, by hand, with local state. Creates:
#   - the S3 bucket that holds Terraform state for every other stack
#   - optionally (enable_github_oidc), the GitHub OIDC provider and the role GitHub Actions assumes
# This stack is never destroyed by the teardown scripts or workflows.

data "aws_caller_identity" "current" {}

resource "aws_s3_bucket" "state" {
  bucket = var.state_bucket_name
}

resource "aws_s3_bucket_versioning" "state" {
  bucket = aws_s3_bucket.state.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_public_access_block" "state" {
  bucket                  = aws_s3_bucket.state.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# --- GitHub Actions deploy role (optional) ---

resource "aws_iam_openid_connect_provider" "github" {
  count           = var.enable_github_oidc && var.create_oidc_provider ? 1 : 0
  url             = "https://token.actions.githubusercontent.com"
  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = ["6938fd4d98bab03faadb97b34396831e3780aea1"]
}

locals {
  oidc_provider_arn = (
    !var.enable_github_oidc
    ? ""
    : var.create_oidc_provider
    ? aws_iam_openid_connect_provider.github[0].arn
    : "arn:aws:iam::${data.aws_caller_identity.current.account_id}:oidc-provider/token.actions.githubusercontent.com"
  )
}

data "aws_iam_policy_document" "github_trust" {
  count = var.enable_github_oidc ? 1 : 0

  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [local.oidc_provider_arn]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    condition {
      test     = "StringLike"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:${var.github_repo}:*"]
    }
  }
}

resource "aws_iam_role" "github" {
  count              = var.enable_github_oidc ? 1 : 0
  name               = "${var.project}-github-actions"
  assume_role_policy = data.aws_iam_policy_document.github_trust[0].json

  lifecycle {
    precondition {
      condition     = var.github_repo != ""
      error_message = "Set github_repo (owner/name) when enable_github_oidc is true."
    }
  }
}

# Demo shortcut: broad permissions so Terraform can create anything it needs.
resource "aws_iam_role_policy_attachment" "github_admin" {
  count      = var.enable_github_oidc ? 1 : 0
  role       = aws_iam_role.github[0].name
  policy_arn = "arn:aws:iam::aws:policy/AdministratorAccess"
}
