output "all_rule_descriptions" {
  description = "Full metadata for all deployed Config rules."
  value       = module.managed_config_rules.all_rule_descriptions
}
