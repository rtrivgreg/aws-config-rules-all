module "managed_config_rules" {
  source = "github.com/niaid/terraform-aws-managed-config-rules?ref=main"

  # Deploy ALL rules from the module's managed_rules map
  # by passing each rule name explicitly via rules_to_include.
  # The module's locals.tf defines 500+ rules — all are listed here.
  rules_to_include = 
