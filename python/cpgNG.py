#!/usr/bin/env python3
"""
cpgNG.py — Generate AWS Config Conformance Pack YAML files from DynamoDB.

Functionally identical to cpg.py, except the Source-of-Truth data layer
reads from the Y62DB single-table DynamoDB catalog instead of a local YAML
file.

Original (cpg.py):
  - --truth-file  → local YAML containing AWS::Config::ConfigRule resources
  - --rules-json  → JSON array of rule name strings
  - --output      → basename for generated pack YAML(s)

This version (cpgNG.py):
  - --table / --region / optional --group / --binding  → DynamoDB catalog
  - --rules-json and --output retain the same semantics
  - All transformation, batching, logical-ID derivation, and YAML emission
    logic is preserved.

DynamoDB expectations (see Y62DB schemas/access-patterns.md and loader):
  Table (default: y62db-config-rule-catalog)
    RULE_PROFILE   pk=RULE#<rule_id>  sk=PROFILE#<rule_id>
    PARAMETER_DEF  pk=RULE#<rule_id>  sk=PARAMDEF#<parameter_name>
    RULE_BINDING   pk=RULE#<rule_id>  sk=GROUP#<group>#BINDING#<binding>
                   (optional; used when --group is supplied)
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import boto3
import yaml
from botocore.exceptions import BotoCoreError, ClientError

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# YAML dumper (identical to cpg.py)
# ---------------------------------------------------------------------------

class BlankLineDumper(yaml.SafeDumper):
    pass


def _dict_representer(dumper: yaml.Dumper, data: dict) -> yaml.nodes.MappingNode:
    return dumper.represent_dict(data)


def _str_representer(dumper: yaml.Dumper, data: str) -> yaml.nodes.ScalarNode:
    return dumper.represent_scalar("tag:yaml.org,2002:str", data)


def _increase_indent(self, flow=False, indentless=False):
    return super(BlankLineDumper, self).increase_indent(flow, False)


BlankLineDumper.add_representer(dict, _dict_representer)
BlankLineDumper.add_representer(str, _str_representer)
BlankLineDumper.increase_indent = _increase_indent


# ---------------------------------------------------------------------------
# Shared helpers (identical to cpg.py)
# ---------------------------------------------------------------------------

def load_rules_json(path: Path) -> List[str]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse JSON from {path}: {e}")
        sys.exit(1)

    if not isinstance(data, list):
        logger.error("Rules JSON must contain a JSON array of strings.")
        sys.exit(1)

    rules: List[str] = []
    for item in data:
        if not isinstance(item, str):
            logger.error("All items in the rules JSON array must be strings.")
            sys.exit(1)
        name = item.strip()
        if not name:
            continue
        rules.append(name)

    if not rules:
        logger.error("No valid rule names found in rules JSON.")
        sys.exit(1)

    return rules


def kebab_to_pascal(name: str) -> str:
    return "".join(p.capitalize() for p in name.split("-") if p)


def derive_logical_id(config_rule_name: str) -> str:
    return kebab_to_pascal(config_rule_name) + "Rule"


def derive_source_identifier_from_name(config_rule_name: str) -> str:
    return config_rule_name.replace("-", "_").upper()


# Render order for AWS::Config::ConfigRule Properties:
#   1 ConfigRuleName
#   2 Description
#   3 Scope
#   5 Source
#   4 InputParameters
PROPERTY_ORDER = (
    "ConfigRuleName",
    "Description",
    "Scope",
    "Source",
    "InputParameters",
)


def order_properties(props: Dict[str, Any]) -> Dict[str, Any]:
    """Return Properties with a stable render order; unknown keys follow."""
    ordered: Dict[str, Any] = {}
    for key in PROPERTY_ORDER:
        if key in props:
            ordered[key] = props[key]
    for key, value in props.items():
        if key not in ordered:
            ordered[key] = value
    return ordered


def ensure_input_parameters_map(resource: Dict[str, Any]) -> None:
    props = resource.get("Properties")
    if not isinstance(props, dict):
        props = {}
        resource["Properties"] = props

    if "InputParameters" not in props or props["InputParameters"] is None:
        props["InputParameters"] = {}
        return

    ip = props["InputParameters"]
    if isinstance(ip, dict):
        return

    props["InputParameters"] = {}


def mutate_resource_in_place(rule_name: str, resource: Dict[str, Any]) -> None:
    resource["Type"] = "AWS::Config::ConfigRule"

    props = resource.get("Properties")
    if not isinstance(props, dict):
        props = {}
        resource["Properties"] = props

    props["ConfigRuleName"] = rule_name

    source_identifier = resolve_source_identifier(rule_name, resource)
    source = props.get("Source")
    if isinstance(source, dict):
        source["Owner"] = "AWS"
        source["SourceIdentifier"] = source_identifier
    else:
        props["Source"] = {
            "Owner": "AWS",
            "SourceIdentifier": source_identifier,
        }

    ensure_input_parameters_map(resource)
    resource["Properties"] = order_properties(resource["Properties"])


def resolve_source_identifier(rule_name: str, resource: Optional[Dict[str, Any]]) -> str:
    if resource:
        props = resource.get("Properties")
        if isinstance(props, dict):
            source = props.get("Source")
            if isinstance(source, dict):
                sid = source.get("SourceIdentifier")
                if isinstance(sid, str):
                    stripped = sid.strip()
                    if stripped:
                        return stripped
    return derive_source_identifier_from_name(rule_name)


def _normalize_description_value(value: str) -> str:
    return " ".join(value.split())


def normalize_descriptions(template: Dict[str, Any]) -> None:
    top_desc = template.get("Description")
    if isinstance(top_desc, str):
        template["Description"] = _normalize_description_value(top_desc)

    resources = template.get("Resources")
    if not isinstance(resources, dict):
        return

    for _, res in resources.items():
        if not isinstance(res, dict):
            continue
        props = res.get("Properties")
        if not isinstance(props, dict):
            continue
        desc = props.get("Description")
        if isinstance(desc, str):
            props["Description"] = _normalize_description_value(desc)


def batch_rules(rule_names: List[str], batch_size: int = 30) -> List[List[str]]:
    return [rule_names[i:i + batch_size] for i in range(0, len(rule_names), batch_size)]


def output_path_for_part(output_path: Path, part_num: int) -> Path:
    return output_path.with_name(f"{output_path.stem}-part{part_num:02d}{output_path.suffix}")


def dump_yaml(data: Dict[str, Any], path: Path) -> None:
    try:
        with path.open("w", encoding="utf-8") as f:
            yaml.dump(
                data,
                f,
                Dumper=BlankLineDumper,
                default_flow_style=False,
                sort_keys=False,
                indent=2,
                width=4096,
            )
    except OSError as e:
        logger.error(f"Failed to write output to {path}: {e}")
        sys.exit(1)
    except yaml.YAMLError as e:
        logger.error(f"Failed to emit YAML to {path}: {e}")
        sys.exit(1)


# ---------------------------------------------------------------------------
# DynamoDB data-source layer  (replaces load_yaml + build_sot_index)
# ---------------------------------------------------------------------------

DEFAULT_TABLE = os.environ.get("CONFIG_RULE_CATALOG_TABLE", "y62db-config-rule-catalog")
DEFAULT_BINDING = "default"


def _get_dynamodb_table(table_name: str, region: Optional[str] = None):
    """Return a boto3 DynamoDB Table resource.

    Region is taken from --region, then AWS_DEFAULT_REGION / AWS_REGION,
    otherwise the default boto3 resolution chain.
    """
    kwargs: Dict[str, Any] = {}
    if region:
        kwargs["region_name"] = region
    resource = boto3.resource("dynamodb", **kwargs)
    return resource.Table(table_name)


def _pk(rule_id: str) -> str:
    return f"RULE#{rule_id}"


def _profile_sk(rule_id: str) -> str:
    return f"PROFILE#{rule_id}"


def _binding_sk(group: str, binding: str) -> str:
    return f"GROUP#{group}#BINDING#{binding}"


def fetch_rule_from_dynamodb(
    table,
    rule_id: str,
    group: Optional[str] = None,
    binding: str = DEFAULT_BINDING,
) -> Optional[Dict[str, Any]]:
    """
    Load one rule's catalog data from DynamoDB and synthesize the same
    resource shape that the original YAML Source-of-Truth provided.

    Returns a dict shaped like:
      {
        "Type": "AWS::Config::ConfigRule",
        "Properties": {
          "ConfigRuleName": ...,
          "Description": ...,
          "Scope": {"ComplianceResourceTypes": [...]},   # if scopes present
          "Source": {"Owner": "AWS", "SourceIdentifier": ...},
          "InputParameters": {...}
        }
      }
    or None if no RULE_PROFILE exists for the rule_id.
    """
    try:
        # 1. RULE_PROFILE
        profile_resp = table.get_item(
            Key={"pk": _pk(rule_id), "sk": _profile_sk(rule_id)}
        )
        profile = profile_resp.get("Item")
        if not profile:
            return None

        # 2. PARAMETER_DEF items (defaults)
        param_resp = table.query(
            KeyConditionExpression="pk = :pk AND begins_with(sk, :prefix)",
            ExpressionAttributeValues={
                ":pk": _pk(rule_id),
                ":prefix": "PARAMDEF#",
            },
        )
        param_defs = param_resp.get("Items", [])

        # 3. Optional RULE_BINDING for group-specific parameter values
        binding_payload: Dict[str, Any] = {}
        if group:
            bind_resp = table.get_item(
                Key={"pk": _pk(rule_id), "sk": _binding_sk(group, binding)}
            )
            bind_item = bind_resp.get("Item")
            if bind_item:
                # payload may contain parameter_values or be the values themselves
                payload = bind_item.get("payload") or {}
                if isinstance(payload, dict):
                    # Prefer an explicit parameter_values key if present
                    binding_payload = payload.get("parameter_values") or payload
                    # Strip non-parameter metadata keys that the API stores
                    for meta in ("status", "version", "scope_values", "created_by"):
                        binding_payload.pop(meta, None)

    except (ClientError, BotoCoreError) as e:
        logger.error(f"DynamoDB error while fetching rule '{rule_id}': {e}")
        sys.exit(1)

    # --- synthesize the CloudFormation resource ---
    source_identifier = (profile.get("source_identifier") or "").strip()
    if not source_identifier:
        source_identifier = derive_source_identifier_from_name(rule_id)

    description = (profile.get("description") or "").strip()

    # Scopes: stored as a list / string-set on RULE_PROFILE
    scopes = profile.get("scopes") or []
    if isinstance(scopes, set):
        scopes = sorted(scopes)
    elif not isinstance(scopes, list):
        scopes = []

    # InputParameters: start from PARAMETER_DEF defaults, then overlay binding
    input_parameters: Dict[str, str] = {}
    for p in param_defs:
        name = p.get("parameter_name")
        if not name:
            continue
        default = p.get("default_value")
        if default is not None and str(default) != "":
            input_parameters[name] = str(default)

    # Binding values take precedence
    for k, v in binding_payload.items():
        if v is None:
            continue
        input_parameters[str(k)] = str(v)

    props: Dict[str, Any] = {
        "ConfigRuleName": rule_id,
        "InputParameters": input_parameters,
        "Source": {
            "Owner": "AWS",
            "SourceIdentifier": source_identifier,
        },
    }

    if description:
        props["Description"] = description

    if scopes:
        props["Scope"] = {"ComplianceResourceTypes": list(scopes)}

    return {
        "Type": "AWS::Config::ConfigRule",
        "Properties": order_properties(props),
    }


def build_sot_index_from_dynamodb(
    table,
    rule_names: List[str],
    group: Optional[str] = None,
    binding: str = DEFAULT_BINDING,
) -> Dict[str, Dict[str, Any]]:
    """
    Build the same index shape that build_sot_index() produced from YAML:
      { config_rule_name: resource_dict, ... }
    """
    index: Dict[str, Dict[str, Any]] = {}
    for rule_name in rule_names:
        resource = fetch_rule_from_dynamodb(table, rule_name, group=group, binding=binding)
        if resource is not None:
            index[rule_name] = resource
        else:
            logger.info(
                f"No RULE_PROFILE found in DynamoDB for '{rule_name}'; "
                "will generate a minimal rule definition."
            )
    return index


# ---------------------------------------------------------------------------
# Pack construction (identical logic to cpg.py)
# ---------------------------------------------------------------------------

def build_pack_template(
    rule_names: List[str],
    sot_index: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    resources: Dict[str, Any] = {}

    for rule_name in rule_names:
        logical_id = derive_logical_id(rule_name)
        existing_resource = sot_index.get(rule_name)

        if logical_id in resources:
            logger.error(f"Duplicate logical ID generated: {logical_id}")
            sys.exit(1)

        if existing_resource is not None:
            # Work on a shallow copy so we don't mutate the shared index entry
            # across multiple packs if the same rule appears more than once.
            resource = {
                "Type": existing_resource.get("Type"),
                "Properties": dict(existing_resource.get("Properties") or {}),
            }
            # Deep-copy nested maps we mutate
            props = resource["Properties"]
            if "Source" in props and isinstance(props["Source"], dict):
                props["Source"] = dict(props["Source"])
            if "InputParameters" in props and isinstance(props["InputParameters"], dict):
                props["InputParameters"] = dict(props["InputParameters"])
            if "Scope" in props and isinstance(props["Scope"], dict):
                props["Scope"] = dict(props["Scope"])
                if "ComplianceResourceTypes" in props["Scope"]:
                    props["Scope"]["ComplianceResourceTypes"] = list(
                        props["Scope"]["ComplianceResourceTypes"]
                    )

            mutate_resource_in_place(rule_name, resource)
            resources[logical_id] = resource
            logger.info(f"Included DynamoDB-backed rule: {rule_name} -> {logical_id}")
        else:
            logger.info(
                f"No DynamoDB entry found for rule '{rule_name}'; "
                "generating without Description, InputParameters, or Scope."
            )
            resources[logical_id] = {
                "Type": "AWS::Config::ConfigRule",
                "Properties": order_properties({
                    "ConfigRuleName": rule_name,
                    "InputParameters": {},
                    "Source": {
                        "Owner": "AWS",
                        "SourceIdentifier": derive_source_identifier_from_name(rule_name),
                    },
                }),
            }

    template = {
        "AWSTemplateFormatVersion": "2010-09-09",
        "Description": "Conformance Pack generated from curated list of AWS Config Managed Rules",
        "Resources": resources,
    }

    normalize_descriptions(template)
    return template


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Generate AWS Config Conformance Pack YAML files from a list of "
            "managed rule names, using the Y62DB DynamoDB catalog as the "
            "Source of Truth (replacement for the YAML truth-file used by cpg.py)."
        )
    )
    parser.add_argument(
        "-r",
        "--rules-json",
        type=Path,
        default=Path("rules01.json"),
        help="JSON file with array of AWS managed Config rule names (default: rules01.json).",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=Path("cpout01.yml"),
        help="Output conformance pack YAML basename (default: cpout01.yml).",
    )
    # DynamoDB-specific arguments (replace --truth-file)
    parser.add_argument(
        "--table",
        default=DEFAULT_TABLE,
        help=(
            f"DynamoDB table name for the rule catalog "
            f"(default: {DEFAULT_TABLE} or env CONFIG_RULE_CATALOG_TABLE)."
        ),
    )
    parser.add_argument(
        "--region",
        default=None,
        help="AWS region for DynamoDB (default: boto3 resolution / env).",
    )
    parser.add_argument(
        "--group",
        default=None,
        help=(
            "Optional organizational group. When supplied, RULE_BINDING "
            "parameter values for this group override PARAMETER_DEF defaults."
        ),
    )
    parser.add_argument(
        "--binding",
        default=DEFAULT_BINDING,
        help=f"Binding identifier under --group (default: {DEFAULT_BINDING}).",
    )

    args = parser.parse_args()

    rule_names = load_rules_json(args.rules_json)

    logger.info(f"Connecting to DynamoDB table '{args.table}'"
                + (f" in region '{args.region}'" if args.region else ""))
    table = _get_dynamodb_table(args.table, args.region)

    # Build the in-memory SOT index from DynamoDB (replaces load_yaml + build_sot_index)
    sot_index = build_sot_index_from_dynamodb(
        table,
        rule_names,
        group=args.group,
        binding=args.binding,
    )
    logger.info(f"Loaded {len(sot_index)} rule definition(s) from DynamoDB.")

    packs = batch_rules(rule_names, 30)
    logger.info(f"Total requested rules: {len(rule_names)}")
    logger.info(f"Total packs to generate: {len(packs)}")

    for idx, pack_rules in enumerate(packs, start=1):
        out_path = output_path_for_part(args.output, idx)
        logger.info(
            f"Generating pack {idx}/{len(packs)} with {len(pack_rules)} rules -> {out_path}"
        )

        template = build_pack_template(pack_rules, sot_index)
        dump_yaml(template, out_path)

        logger.info(f"Wrote {out_path}")

    logger.info(f"Generated {len(packs)} conformance pack file(s) successfully.")


if __name__ == "__main__":
    main()
