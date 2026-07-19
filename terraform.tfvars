aws_region           = "us-east-1"
organization_managed = false
rule_name_prefix     = "rshl-"
max_access_key_age   = 90
master_account_id    = null

tags = {
  ManagedBy   = "Terraform"
  Project     = "config-rules"
  Environment = "poc"
  Service     = "aws-config"
}
