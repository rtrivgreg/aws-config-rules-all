#!/usr/bin/env python3
import argparse
import re
from pathlib import Path

import hcl2


DEFAULT_RULES_LOCALS = "vendor/niaid/managed_rules_locals.tf"
DEFAULT_RULES_VARIABLES = "vendor/niaid/managed_rules_variables.tf"


def existing_file(path_str: str) -> Path:
    path = Path(path_str).expanduser()
    if not path.is_file():
        raise argparse.ArgumentTypeError(f"File does not exist: {path}")
    return path


def parse_args():
    parser = argparse.ArgumentParser(
        description="Generate an AWS Config conformance pack YAML from Terraform managed rules and variable definitions."
    )

    parser.add_argument(
        "--managed-rules-locals",
        type=existing_file,
        default=Path(DEFAULT_RULES_LOCALS),
        help=f"Path to managed_rules_locals.tf (default: {DEFAULT_RULES_LOCALS})",
    )

    parser.add_argument(
        "--managed-rules-variables",
        type=existing_file,
        default=Path(DEFAULT_RULES_VARIABLES),
        help=f"Path to managed_rules_variables.tf (default: {DEFAULT_RULES_VARIABLES})",
    )

    parser.add_argument(
        "--format",
        required=True,
        type=existing_file,
        help="Path to the conformance pack YAML format/header file",
    )

    parser.add_argument(
        "--output",
        required=True,
        type=Path,
        help="Path to write generated YAML",
    )

    parser.add_argument(
        "--description",
        default="Y62 Truth Manifest",
        help="Top-level template description",
    )

    parser.add_argument(
        "--rule-limit",
        type=int,
        default=0,
        help="Optional limit for number of rules to render, useful for testing",
    )

    parser.add_argument(
        "--debug",
        action="store_true",
        help="Print debug information about parsed HCL and variable extraction",
    )

    return parser.parse_args()


def clean_hcl_string(value):
    if not isinstance(value, str):
        return value

    value = value.strip()

    if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
        return value[1:-1]

    if len(value) >= 2 and value[0] == "'" and value[-1] == "'":
        return value[1:-1]

    return value


def load_hcl_file(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return hcl2.load(f)


def load_managed_rules(locals_path: Path) -> dict:
    data = load_hcl_file(locals_path)
    return data["locals"][0]["managed_rules"]


def load_parameter_variables_text(variables_path: Path) -> str:
    return variables_path.read_text(encoding="utf-8")


def normalize_managed_rules(managed_rules: dict) -> list[dict]:
    normalized = []

    for rule_name, rule_def in managed_rules.items():
        input_ref = rule_def.get("input_parameters")
        input_var = None

        if isinstance(input_ref, str):
            input_ref = clean_hcl_string(input_ref)
            if input_ref.startswith("${var.") and input_ref.endswith("}"):
                input_var = input_ref[6:-1]
            elif input_ref.startswith("var."):
                input_var = input_ref[4:]

        normalized.append(
            {
                "name": clean_hcl_string(rule_name),
                "identifier": clean_hcl_string(rule_def.get("identifier")),
                "description": clean_hcl_string(rule_def.get("description", "")),
                "severity": clean_hcl_string(rule_def.get("severity")),
                "scopes": [clean_hcl_string(x) for x in rule_def.get("resource_types_scope", [])],
                "input_var": input_var,
            }
        )

    return normalized


def normalize_parameter_variables_from_text(params_text: str) -> dict:
    var_pattern = re.compile(
        r'variable\s+"([A-Za-z0-9_]+)"\s*{(.*?)(?=^variable\s+"|\Z)',
        re.S | re.M,
    )

    optional_attr_pattern = re.compile(
        r'([A-Za-z0-9_]+)\s*=\s*optional\((string|number|bool|boolean)(?:,\s*([^)]+))?\)'
    )

    default_block_pattern = re.compile(
        r'default\s*=\s*{(.*?)}',
        re.S,
    )

    normalized = {}

    for var_name, body in var_pattern.findall(params_text):
        if not var_name.endswith("_parameters"):
            continue

        attrs = []
        type_block = re.search(r'type\s*=\s*object\(\s*{(.*?)}\s*\)', body, re.S)
        if type_block:
            for key, typ, default in optional_attr_pattern.findall(type_block.group(1)):
                attrs.append(
                    {
                        "name": key,
                        "type": typ,
                        "default": default.strip() if default else None,
                    }
                )

        defaults = {}
        default_block = default_block_pattern.search(body)
        if default_block:
            for line in default_block.group(1).splitlines():
                line = line.strip().rstrip(",")
                if not line or "=" not in line:
                    continue
                key, value = [x.strip() for x in line.split("=", 1)]
                defaults[key] = clean_hcl_string(value)

        normalized[var_name] = {
            "attrs": attrs,
            "default": defaults,
        }

    return normalized


def logical_name(rule_name: str) -> str:
    return "".join(
        part.capitalize() for part in re.split(r"[^a-zA-Z0-9]", rule_name) if part
    ) + "Rule"


def yaml_quote(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def yaml_scalar(value):
    if value is None:
        return None

    if isinstance(value, bool):
        return "true" if value else "false"

    if isinstance(value, (int, float)):
        return str(value)

    if isinstance(value, str):
        raw = clean_hcl_string(value).strip()
        lowered = raw.lower()

        if lowered == "null":
            return None
        if lowered in ("true", "false"):
            return lowered
        if re.fullmatch(r"-?\d+", raw):
            return yaml_quote(raw)
        if re.fullmatch(r"-?\d+\.\d+", raw):
            return yaml_quote(raw)

        return yaml_quote(raw)

    return yaml_quote(str(value))


def placeholder_for_key(key: str) -> str:
    lowered = key.lower()

    if "arn" in lowered:
        return '"optional_arn"'
    if "account" in lowered and "id" in lowered:
        return '"optional_account_id"'
    if lowered.endswith("ids"):
        return '"optional_ids_csv"'
    if lowered.endswith("arns"):
        return '"optional_arns_csv"'
    if "tag" in lowered:
        return '"optional_tag_list"'
    if "days" in lowered or "age" in lowered or "period" in lowered or "threshold" in lowered:
        return "0"
    if "enabled" in lowered or lowered.startswith("is") or lowered.startswith("allow"):
        return "false"

    return '"optional_string"'


def render_input_parameters(rule: dict, param_defs: dict) -> list[str]:
    input_var = rule.get("input_var")
    if not input_var:
        return []

    var_def = param_defs.get(input_var)
    if not var_def:
        return ["      InputParameters: {}"]

    defaults = var_def.get("default", {})
    attrs = var_def.get("attrs", [])

    if defaults:
        lines = ["      InputParameters:"]
        for key, value in defaults.items():
            rendered = yaml_scalar(value)
            if rendered is None:
                rendered = placeholder_for_key(key)
            lines.append(f"        {key}: {rendered}")
        return lines

    if attrs:
        lines = ["      InputParameters:"]
        for attr in attrs:
            default = attr.get("default")
            if default is not None and clean_hcl_string(default).lower() != "null":
                rendered = yaml_scalar(default)
            else:
                rendered = placeholder_for_key(attr["name"])
            lines.append(f"        {attr['name']}: {rendered}")
        return lines

    return ["      InputParameters: {}"]


def render_rule(rule: dict, param_defs: dict) -> list[str]:
    lines = []
    lines.append(f"  {logical_name(rule['name'])}:")
    lines.append("    Type: AWS::Config::ConfigRule")
    lines.append("    Properties:")
    lines.append(f"      ConfigRuleName: {rule['name']}")
    lines.append(f"      Description: {yaml_quote(rule['description'])}")

    if rule["scopes"]:
        lines.append("      Scope:")
        lines.append("        ComplianceResourceTypes:")
        for scope in rule["scopes"]:
            lines.append(f"          - {scope}")

    lines.append("      Source:")
    lines.append("        Owner: AWS")
    lines.append(f"        SourceIdentifier: {rule['identifier']}")

    lines.extend(render_input_parameters(rule, param_defs))
    return lines


def build_template(format_text: str, description: str, rules: list[dict], param_defs: dict) -> str:
    output = []

    fmt_version = re.search(r"AWSTemplateFormatVersion:\s*'?([^'\n]+)'?", format_text)
    template_version = fmt_version.group(1) if fmt_version else "2010-09-09"

    output.append(f"AWSTemplateFormatVersion: '{template_version}'")
    output.append(f"Description: {yaml_quote(description)}")
    output.append("Resources:")

    for rule in rules:
        output.extend(render_rule(rule, param_defs))
        output.append("")

    return "\n".join(output).rstrip() + "\n"


def main():
    args = parse_args()

    managed_rules_raw = load_managed_rules(args.managed_rules_locals)
    params_text = load_parameter_variables_text(args.managed_rules_variables)
    format_text = args.format.read_text(encoding="utf-8")

    rules = normalize_managed_rules(managed_rules_raw)
    param_defs = normalize_parameter_variables_from_text(params_text)

    if args.rule_limit > 0:
        rules = rules[: args.rule_limit]

    if args.debug:
        print(f"Loaded {len(managed_rules_raw)} managed rules from {args.managed_rules_locals}")
        print(f"Loaded {len(param_defs)} parameter variables from {args.managed_rules_variables}")
        if rules:
            print("Sample normalized rule:", rules[0])
        print("access_keys_rotated_parameters =", repr(param_defs.get("access_keys_rotated_parameters")))
        print("account_part_of_organizations_parameters =", repr(param_defs.get("account_part_of_organizations_parameters")))

    rendered = build_template(
        format_text=format_text,
        description=args.description,
        rules=rules,
        param_defs=param_defs,
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(rendered, encoding="utf-8")

    print(f"Wrote {args.output} with {len(rules)} rules.")


if __name__ == "__main__":
    main()