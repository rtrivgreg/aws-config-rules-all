#!/usr/bin/env python3
"""Generate an AWS Config conformance pack from NIAID Terraform rule metadata."""

import argparse
import re
import sys
from pathlib import Path
from typing import Any

import hcl2


DEFAULT_RULES_LOCALS = "vendor/niaid/managed_rules_locals.tf"
DEFAULT_RULES_VARIABLES = "vendor/niaid/managed_rules_variables.tf"
MAX_CONFIG_RULE_DESCRIPTION_LENGTH = 256


def existing_file(path_str: str) -> Path:
    path = Path(path_str).expanduser()
    if not path.is_file():
        raise argparse.ArgumentTypeError(f"File does not exist: {path}")
    return path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Generate an AWS Config conformance pack YAML from Terraform "
            "managed-rule and variable definitions."
        )
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
        help=(
            "Path to managed_rules_variables.tf "
            f"(default: {DEFAULT_RULES_VARIABLES})"
        ),
    )
    parser.add_argument(
        "--format",
        required=True,
        type=existing_file,
        help="Path to the conformance-pack YAML format/header file",
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
        help="Optional rule limit, useful for testing",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Print parsed-variable and rule diagnostics",
    )
    return parser.parse_args()


def clean_hcl_string(value: Any) -> Any:
    if not isinstance(value, str):
        return value

    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value


def parse_hcl_literal(value: str | None) -> Any:
    """Parse the simple scalar literals used as Config rule defaults."""
    if value is None:
        return None

    raw = value.strip().rstrip(",")
    lowered = raw.lower()

    if lowered == "null":
        return None
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if re.fullmatch(r"-?\d+", raw):
        return int(raw)
    if re.fullmatch(r"-?(?:\d+\.\d*|\d*\.\d+)", raw):
        return float(raw)
    return clean_hcl_string(raw)


def load_hcl_file(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as file:
        return hcl2.load(file)


def load_managed_rules(locals_path: Path) -> dict:
    data = load_hcl_file(locals_path)
    try:
        return data["locals"][0]["managed_rules"]
    except (KeyError, IndexError, TypeError) as error:
        raise ValueError(
            f"Could not find locals.managed_rules in {locals_path}"
        ) from error


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
                "description": clean_hcl_string(
                    rule_def.get("description", "")
                ),
                "severity": clean_hcl_string(rule_def.get("severity")),
                "scopes": [
                    clean_hcl_string(item)
                    for item in rule_def.get("resource_types_scope", [])
                ],
                "input_var": input_var,
            }
        )

    return normalized


def extract_variable_blocks(params_text: str) -> list[tuple[str, str]]:
    pattern = re.compile(
        r'variable\s+"([A-Za-z0-9_]+)"\s*{(.*?)(?=^variable\s+"|\Z)',
        re.S | re.M,
    )
    return pattern.findall(params_text)


def extract_type_object(body: str) -> str | None:
    match = re.search(
        r"type\s*=\s*object\s*\(\s*{(.*?)}\s*\)",
        body,
        re.S,
    )
    return match.group(1) if match else None


def extract_outer_defaults(body: str) -> dict[str, Any]:
    match = re.search(r"default\s*=\s*{(.*?)}", body, re.S)
    if not match:
        return {}

    defaults: dict[str, Any] = {}
    assignment_pattern = re.compile(
        r"^\s*([A-Za-z0-9_]+)\s*=\s*(.*?)\s*,?\s*(?:#.*)?$",
        re.M,
    )
    for key, raw_value in assignment_pattern.findall(match.group(1)):
        defaults[key] = parse_hcl_literal(raw_value)
    return defaults


def extract_attributes(type_text: str) -> list[dict]:
    """
    Parse primitive object attributes while preserving declaration order.

    Supported forms:
      name = string
      name = optional(string)
      name = optional(string, null)
      name = optional(number, 1)
    """
    attribute_pattern = re.compile(
        r"""
        ^\s*(?P<name>[A-Za-z0-9_]+)\s*=\s*
        (?:
            optional\(
                \s*(?P<optional_type>string|number|bool|boolean)
                (?:\s*,\s*(?P<inline_default>[^)]+))?
                \s*
            \)
          |
            (?P<required_type>string|number|bool|boolean)
        )
        \s*,?\s*(?:\#.*)?$
        """,
        re.M | re.X,
    )

    attributes = []
    for match in attribute_pattern.finditer(type_text):
        declared_optional = match.group("optional_type") is not None
        attribute_type = (
            match.group("optional_type") or match.group("required_type")
        )
        inline_default = parse_hcl_literal(match.group("inline_default"))

        attributes.append(
            {
                "name": match.group("name"),
                "type": attribute_type,
                "declared_optional": declared_optional,
                "inline_default": inline_default,
            }
        )

    return attributes


def normalize_parameter_variables_from_text(params_text: str) -> dict:
    normalized = {}

    for variable_name, body in extract_variable_blocks(params_text):
        if not variable_name.endswith("_parameters"):
            continue

        outer_defaults = extract_outer_defaults(body)
        type_text = extract_type_object(body)
        attributes = extract_attributes(type_text) if type_text else []

        normalized_attributes = []
        for attribute in attributes:
            name = attribute["name"]

            if name in outer_defaults:
                effective_default = outer_defaults[name]
                default_source = "variable"
            elif attribute["inline_default"] is not None:
                effective_default = attribute["inline_default"]
                default_source = "attribute"
            else:
                effective_default = None
                default_source = None

            # Emitter semantics requested by the manifest design:
            # - HCL-required attributes are required.
            # - Optional attributes with non-null defaults are emitted as
            #   required manifest parameters.
            # - Optional attributes with no effective value are metadata-only
            #   and must not be emitted in InputParameters.
            emit_parameter = (
                not attribute["declared_optional"]
                or effective_default is not None
            )

            normalized_attributes.append(
                {
                    **attribute,
                    "default": effective_default,
                    "default_source": default_source,
                    "emit_parameter": emit_parameter,
                }
            )

        known_names = {
            attribute["name"] for attribute in normalized_attributes
        }
        default_only = [
            {
                "name": name,
                "type": infer_type(value),
                "declared_optional": False,
                "inline_default": None,
                "default": value,
                "default_source": "variable",
                "emit_parameter": value is not None,
            }
            for name, value in outer_defaults.items()
            if name not in known_names
        ]

        normalized[variable_name] = {
            "attrs": normalized_attributes + default_only,
            "default": outer_defaults,
        }

    return normalized


def infer_type(value: Any) -> str:
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, (int, float)):
        return "number"
    return "string"


def logical_name(rule_name: str) -> str:
    return "".join(
        part.capitalize()
        for part in re.split(r"[^a-zA-Z0-9]", rule_name)
        if part
    ) + "Rule"


def yaml_quote(value: str) -> str:
    escaped = (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
    )
    return f'"{escaped}"'


def yaml_scalar(value: Any) -> str:
    """
    Render every Config input parameter as a YAML string.

    AWS Config input parameter values are string-valued, even when the
    Terraform variable uses number or bool for validation.
    """
    if value is None:
        raise ValueError("Cannot render null as an AWS Config input parameter")
    if isinstance(value, bool):
        return yaml_quote("true" if value else "false")
    return yaml_quote(str(value))


def optional_parameter_prefix(
    rule: dict,
    param_defs: dict,
) -> str:
    input_var = rule.get("input_var")
    variable = param_defs.get(input_var, {})
    optional_attributes = [
        f'{attribute["name"]} ({attribute["type"]})'
        for attribute in variable.get("attrs", [])
        if (
            attribute.get("declared_optional")
            and not attribute.get("emit_parameter")
        )
    ]

    if not optional_attributes:
        return ""
    return f"Optional parameters: {', '.join(optional_attributes)}. "


def build_rule_description(rule: dict, param_defs: dict) -> str:
    """Prepend optional metadata without exceeding AWS Config's limit."""
    prefix = optional_parameter_prefix(rule, param_defs)
    original = rule["description"]

    if len(prefix) > MAX_CONFIG_RULE_DESCRIPTION_LENGTH:
        raise ValueError(
            f"Rule {rule['name']!r} has an optional-parameter prefix longer "
            f"than {MAX_CONFIG_RULE_DESCRIPTION_LENGTH} characters"
        )

    available = MAX_CONFIG_RULE_DESCRIPTION_LENGTH - len(prefix)
    if len(original) <= available:
        return f"{prefix}{original}"

    if available <= 3:
        return prefix[:MAX_CONFIG_RULE_DESCRIPTION_LENGTH]

    return f"{prefix}{original[: available - 3].rstrip()}..."


def render_input_parameters(
    rule: dict,
    param_defs: dict,
) -> list[str]:
    input_var = rule.get("input_var")
    if not input_var:
        return []

    variable = param_defs.get(input_var)
    if variable is None:
        raise ValueError(
            f"Rule {rule['name']!r} references undefined variable "
            f"{input_var!r}"
        )

    emitted = []
    for attribute in variable.get("attrs", []):
        if not attribute.get("emit_parameter"):
            continue

        value = attribute.get("default")
        if value is None:
            raise ValueError(
                f"Rule {rule['name']!r} has required parameter "
                f"{attribute['name']!r}, but no non-null default is defined"
            )
        emitted.append((attribute["name"], value))

    if not emitted:
        return []

    lines = ["      InputParameters:"]
    lines.extend(
        f"        {name}: {yaml_scalar(value)}"
        for name, value in emitted
    )
    return lines


def render_rule(rule: dict, param_defs: dict) -> list[str]:
    description = build_rule_description(rule, param_defs)

    lines = [
        f"  {logical_name(rule['name'])}:",
        "    Type: AWS::Config::ConfigRule",
        "    Properties:",
        f"      ConfigRuleName: {rule['name']}",
        f"      Description: {yaml_quote(description)}",
    ]

    if rule["scopes"]:
        lines.extend(
            [
                "      Scope:",
                "        ComplianceResourceTypes:",
            ]
        )
        lines.extend(f"          - {scope}" for scope in rule["scopes"])

    lines.extend(
        [
            "      Source:",
            "        Owner: AWS",
            f"        SourceIdentifier: {rule['identifier']}",
        ]
    )
    lines.extend(render_input_parameters(rule, param_defs))
    return lines


def build_template(
    format_text: str,
    description: str,
    rules: list[dict],
    param_defs: dict,
) -> str:
    version_match = re.search(
        r"AWSTemplateFormatVersion:\s*'?([^'\n]+)'?",
        format_text,
    )
    template_version = (
        version_match.group(1).strip()
        if version_match
        else "2010-09-09"
    )

    output = [
        f"AWSTemplateFormatVersion: '{template_version}'",
        f"Description: {yaml_quote(description)}",
        "Resources:",
    ]

    for index, rule in enumerate(rules):
        output.extend(render_rule(rule, param_defs))
        if index != len(rules) - 1:
            output.append("")

    return "\n".join(output) + "\n"


def main() -> int:
    args = parse_args()

    try:
        managed_rules_raw = load_managed_rules(
            args.managed_rules_locals
        )
        params_text = args.managed_rules_variables.read_text(
            encoding="utf-8"
        )
        format_text = args.format.read_text(encoding="utf-8")

        rules = normalize_managed_rules(managed_rules_raw)
        param_defs = normalize_parameter_variables_from_text(params_text)

        if args.rule_limit > 0:
            rules = rules[: args.rule_limit]

        if args.debug:
            print(
                f"Loaded {len(managed_rules_raw)} managed rules from "
                f"{args.managed_rules_locals}",
                file=sys.stderr,
            )
            print(
                f"Loaded {len(param_defs)} parameter variables from "
                f"{args.managed_rules_variables}",
                file=sys.stderr,
            )
            print(
                "aurora_last_backup_recovery_point_created_parameters =",
                repr(
                    param_defs.get(
                        "aurora_last_backup_recovery_point_created_parameters"
                    )
                ),
                file=sys.stderr,
            )
            print(
                "account_part_of_organizations_parameters =",
                repr(
                    param_defs.get(
                        "account_part_of_organizations_parameters"
                    )
                ),
                file=sys.stderr,
            )

        rendered = build_template(
            format_text=format_text,
            description=args.description,
            rules=rules,
            param_defs=param_defs,
        )

        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
        print(f"Wrote {args.output} with {len(rules)} rules.")
        return 0

    except (OSError, KeyError, TypeError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
