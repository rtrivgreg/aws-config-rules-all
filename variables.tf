variable "aws_region" {
  description = "AWS region to deploy Config rules into."
  type        = string
  default     = "us-east-1"
}

variable "organization_managed" {
  description = "Whether to create organization-managed Config rules."
  type        = bool
  default     = false
}

variable "rule_name_prefix" {
  description = "String prefix added to all Config rule names."
  type        = string
  default     = ""
}

variable "max_access_key_age" {
  description = "Maximum days an IAM access key can exist before flagged non-compliant."
  type        = number
  default     = 90
}

variable "master_account_id" {
  description = "AWS Organizations master account ID. Leave null if not restricting."
  type        = string
  default     = null
}

variable "tags" {
  description = "Tags to apply to all Config rules."
  type        = map(string)
  default     = {}
}
