# Bucket and region are passed at init time (see scripts/tf.sh):
#   terraform init -backend-config="bucket=<state bucket>" -backend-config="region=<region>"
terraform {
  backend "s3" {
    key          = "base/terraform.tfstate"
    use_lockfile = true
  }
}
