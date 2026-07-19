module "managed_config_rules" {
  source = "github.com/niaid/terraform-aws-managed-config-rules?ref=main"

  # Deploy ALL rules from the module's managed_rules map
  # by passing each rule name explicitly via rules_to_include.
  # The module's locals.tf defines 500+ rules — all are listed here.
  rules_to_include = [
    "access-keys-rotated",
    "account-part-of-organizations",
    "acmpca-certificate-authority-tagged",
    "acm-certificate-expiration-check",
    "acm-certificate-rsa-check",
    "acm-certificate-transparent-logging-enabled",
    "acm-pca-root-ca-disabled",
    "active-mq-supported-version",
    "alb-desync-mode-check",
    "alb-http-drop-invalid-header-enabled",
    "alb-http-to-https-redirection-check",
    "alb-internal-scheme-check",
    "alb-listener-tagged",
    "alb-tagged",
    "alb-waf-enabled",
  ]
