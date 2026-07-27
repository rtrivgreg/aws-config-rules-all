#!/usr/bin/env python3
import argparse
import re
from pathlib import Path


def existing_file(path_str: str) -> Path:
    path = Path(path_str)
    if not path.is_file():
        raise argparse.ArgumentTypeError(f"File does not exist: {path}")
    return path


def parse_args():
    parser = argparse.ArgumentParser(
        description="Generate an AWS Config conformance pack YAML from Terraform rule and parameter definitions."
    )
    parser.add_argument(
        "--rules",
        required=True,
        type=existing_file,
        help="Path to file containing locals.managed_rules",
    )
    parser.add_argument(
        "--params",
        required=True,
        type=existing_file,
        help="Path to file containing variable *_parameters blocks",
    )
    parser.add_argument(
        "--format",
        required=True,
        type=existing_file,
        help="Path to file containing the exact conformance pack YAML format/header to follow",
    )
    parser.add_argument(
        "--output",
        required=True,
        help="Path to write generated YAML",
    )
    parser.add_argument(
        "--description",
        default="Y62 Truth Manifest\n",
        help="Top-level template description",
    )
    return parser.parse_args()


def extract_managed_rules_block(text: str) -> str:
    match = re.search(
        r"locals\s*{\s*managed_rules\s*=\s*{(.*)}\s*}\s*$",
        text,
        re.S,
    )
    if not match:
        raise ValueError("Could not find locals { managed_rules = { ... } } block")
    return match.group(1)


def parse_rules(rules_text: str):
    block = extract_managed_rules_block(rules_text)

    rule_pattern = re.compile(r"(?ms)^\s*([a-z0-9-]+)\s*=\s*{(.*?)^\s*}")
    identifier_pattern = re.compile(r'identifier\s*=\s*"([A-Z0-9_]+)"')
    input_pattern = re.compile(r"input_parameters\s*=\s*var\.([a-z0-9_]+)")
    scope_pattern = re.compile(r"resource_types_scope\s*=\s*\[(.*?)\]", re.S)
    desc_pattern = re.compile(r'description\s*=\s*"([^"]*)"')
    severity_pattern = re.compile(r'severity\s*=\s*"([^"]+)"')

    rules = []
    for name, body in rule_pattern.findall(block):
        ident = identifier_pattern.search(body)
        if not ident:
            continue

        input_m = input_pattern.search(body)
        scope_m = scope_pattern.search(body)
        desc_m = desc_pattern.search(body)
        sev_m = severity_pattern.search(body)

        scopes = re.findall(r'"([^"]+)"', scope_m.group(1)) if scope_m else []

        rules.append(
            {
                "name": name,
                "identifier": ident.group(1),
                "input_var": input_m.group(1) if input_m else None,
                "description": desc_m.group(1) if desc_m else "",
                "severity": sev_m.group(1) if sev_m else None,
                "scopes": scopes,
            }
        )

    return rules


def parse_param_variables(params_text: str):
    var_pattern = re.compile(
        r'variable\s+"([a-zA-Z0-9_]+)"\s*{(.*?)^}',
        re.S | re.M,
    )
    attr_pattern = re.compile(
        r"([A-Za-z0-9_]+)\s*=\s*optional\((string|number|bool|boolean)(?:,\s*([^)]+))?\)"
    )

    results = {}
    for var_name, body in var_pattern.findall(params_text):
        attrs = []
        type_block = re.search(r"type\s*=\s*object\(\s*{(.*?)}\s*\)", body, re.S)
        if type_block:
            for key, typ, default in attr_pattern.findall(type_block.group(1)):
                attrs.append(
                    {
                        "name": key,
                        "type": typ,
                        "default": default.strip() if default else None,
                    }
                )
        results[var_name] = attrs
    return results


def logical_name(rule_name: str) -> str:
    return "".join(part.capitalize() for part in re.split(r"[^a-zA-Z0-9]", rule_name) if part) + "Rule"


def yaml_scalar(value: str, value_type: str):
    if value is None or value == "null":
        return None
    raw = value.strip().strip('"')
    if value_type in ("number",):
        try:
            return str(int(raw)) if "." not in raw else str(float(raw))
        except ValueError:
            return raw
    if value_type in ("bool", "boolean"):
        return raw.lower()
    return raw


def render_rule(rule: dict, param_defs: dict) -> list[str]:
    lines = []
    lines.append(f"  {logical_name(rule['name'])}:")
    lines.append("    Type: AWS::Config::ConfigRule")
    lines.append("    Properties:")
    lines.append(f"      ConfigRuleName: {rule['name']}")
    lines.append(f"      Description: {rule['description']}")

    if rule["scopes"]:
        lines.append("      Scope:")
        lines.append("        ComplianceResourceTypes:")
        for scope in rule["scopes"]:
            lines.append(f"          - {scope}")

    lines.append("      Source:")
    lines.append("        Owner: AWS")
    lines.append(f"        SourceIdentifier: {rule['identifier']}")

    if rule["input_var"]:
        attrs = param_defs.get(rule["input_var"], [])
        lines.append("      InputParameters:")
        if attrs:
            for attr in attrs:
                val = yaml_scalar(attr["default"], attr["type"])
                if val is None:
                    lines.append(f"        {attr['name']}: optional_{attr['type']}")
                else:
                    lines.append(f"        {attr['name']}: {val}")
        else:
            lines.append("        {}")

    return lines


def build_template(format_text: str, description: str, rules: list[dict], param_defs: dict) -> str:
    output = []

    fmt_version = re.search(r"AWSTemplateFormatVersion:\s*'?([^'\n]+)'?", format_text)
    desc = re.search(r'Description:\s*"?(.*?)"?\s*$', format_text, re.M)

    output.append(f"AWSTemplateFormatVersion: '{fmt_version.group(1) if fmt_version else '2010-09-09'}'")
    output.append(f'Description: "{description}"')
    output.append("Resources:")

    for rule in rules:
        output.extend(render_rule(rule, param_defs))
        output.append("")

    return "\n".join(output).rstrip() + "\n"


def main():
    args = parse_args()

    rules_text = args.rules.read_text()
    params_text = args.params.read_text()
    format_text = args.format.read_text()

    rules = parse_rules(rules_text)
    param_defs = parse_param_variables(params_text)
    rendered = build_template(format_text, args.description, rules, param_defs)

    Path(args.output).write_text(rendered)
    print(f"Wrote {args.output} with {len(rules)} rules.")


if __name__ == "__main__":
    main()
