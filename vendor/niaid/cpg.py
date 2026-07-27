import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Dict, List, Optional

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# YAML (ruamel) helper
# ---------------------------------------------------------------------------

yaml_rt = YAML(typ="rt")        # round-trip to preserve comments and order
yaml_rt.indent(mapping=2, sequence=4, offset=2)
yaml_rt.width = 4096            # keep long scalars like Description on one line
yaml_rt.representer.ignore_aliases = lambda x: True  # suppress &id001 / *id001

# ---------------------------------------------------------------------------
# Load JSON rules
# ---------------------------------------------------------------------------


def load_rules_json(path: Path) -> List[str]:
    """Load JSON array of rule names (strings)."""
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


# ---------------------------------------------------------------------------
# Load YAML SOT via ruamel.yaml
# ---------------------------------------------------------------------------


def load_yaml(path: Path) -> CommentedMap:
    """Load a YAML file with ruamel.yaml (round-trip) and ensure top-level is a mapping."""
    try:
        with path.open("r", encoding="utf-8") as f:
            data = yaml_rt.load(f)
    except Exception as e:
        logger.error(f"Failed to parse YAML from {path}: {e}")
        sys.exit(1)

    if data is None:
        data = CommentedMap()

    if not isinstance(data, CommentedMap):
        logger.error(f"Top-level YAML structure in {path} must be a mapping.")
        sys.exit(1)

    return data


# ---------------------------------------------------------------------------
# Helper name transformations
# ---------------------------------------------------------------------------


def kebab_to_pascal(name: str) -> str:
    """Convert kebab-case to PascalCase."""
    parts = name.split("-")
    return "".join(p.capitalize() for p in parts if p)


def derive_logical_id(config_rule_name: str) -> str:
    """Derive CloudFormation logical ID from ConfigRuleName."""
    return kebab_to_pascal(config_rule_name) + "Rule"


def derive_source_identifier_from_name(config_rule_name: str) -> str:
    """Derive SourceIdentifier from ConfigRuleName."""
    return config_rule_name.replace("-", "_").upper()


# ---------------------------------------------------------------------------
# Build SOT index (ConfigRuleName -> resource_map)
# ---------------------------------------------------------------------------


def build_sot_index(sot: CommentedMap) -> Dict[str, CommentedMap]:
    resources = sot.get("Resources")
    if resources is None:
        return {}

    if not isinstance(resources, CommentedMap):
        logger.warning(
            "SOT has Resources, but it is not a mapping; SOT will be ignored."
        )
        return {}

    index: Dict[str, CommentedMap] = {}

    for _, res in resources.items():
        if not isinstance(res, CommentedMap):
            continue
        if res.get("Type") != "AWS::Config::ConfigRule":
            continue
        props = res.get("Properties")
        if not isinstance(props, CommentedMap):
            continue
        name = props.get("ConfigRuleName")
        if not isinstance(name, str):
            continue
        name = name.strip()
        if not name:
            continue
        index[name] = res

    return index

# ---------------------------------------------------------------------------
# SourceIdentifier resolution
# ---------------------------------------------------------------------------


def resolve_source_identifier(
    rule_name: str,
    resource: Optional[CommentedMap],
) -> str:
    """
    Apply the SourceIdentifier override rule:

    - If SOT resource Properties contain a non-empty Source.SourceIdentifier, use it.
    - Otherwise derive from the rule_name (ConfigRuleName).
    """
    if resource:
        props = resource.get("Properties")
        if isinstance(props, CommentedMap):
            source = props.get("Source")
            if isinstance(source, CommentedMap):
                sid = source.get("SourceIdentifier")
                if isinstance(sid, str):
                    stripped = sid.strip()
                    if stripped:
                        return stripped
    return derive_source_identifier_from_name(rule_name)


# ---------------------------------------------------------------------------
# InputParameters normalization
# ---------------------------------------------------------------------------


def ensure_input_parameters_map(resource: CommentedMap) -> None:
    """
    Ensure Properties.InputParameters is an explicit empty map ({}) when present
    but empty/null, so the output consistently means:
      'this field exists, but currently has no active parameters'.

    This avoids InputParameters: null and preserves a stable mapping shape.
    """
    props = resource.get("Properties")
    if not isinstance(props, CommentedMap):
        props = CommentedMap()
        resource["Properties"] = props

    if "InputParameters" in props:
        if props["InputParameters"] is None:
            props["InputParameters"] = CommentedMap()
        elif not isinstance(props["InputParameters"], CommentedMap):
            if props["InputParameters"] == {}:
                props["InputParameters"] = CommentedMap()


# ---------------------------------------------------------------------------
# Mutate an existing SOT resource in-place
# ---------------------------------------------------------------------------


def mutate_resource_in_place(
    rule_name: str,
    resource: CommentedMap,
) -> None:
    """
    Mutate the existing SOT resource in-place to conform to our generation rules,
    while preserving all comments on the resource, its Properties, and
    nested mappings such as InputParameters.

    Changes:
    - Ensure Type is AWS::Config::ConfigRule.
    - Ensure Properties.ConfigRuleName == rule_name.
    - Ensure Properties.Source.Owner == 'AWS'.
    - Ensure Properties.Source.SourceIdentifier is set according to rules.
    - Ensure InputParameters, if present, is an explicit empty map instead of null.
    """
    resource["Type"] = "AWS::Config::ConfigRule"

    props = resource.get("Properties")
    if not isinstance(props, CommentedMap):
        props = CommentedMap()
        resource["Properties"] = props

    props["ConfigRuleName"] = rule_name

    source_identifier = resolve_source_identifier(rule_name, resource)
    source = props.get("Source")
    if isinstance(source, CommentedMap):
        source["Owner"] = "AWS"
        source["SourceIdentifier"] = source_identifier
    else:
        source_map = CommentedMap()
        source_map["Owner"] = "AWS"
        source_map["SourceIdentifier"] = source_identifier
        props["Source"] = source_map

    ensure_input_parameters_map(resource)


# ---------------------------------------------------------------------------
# Description normalization helper
# ---------------------------------------------------------------------------


def _normalize_description_value(value: str) -> str:
    """
    Normalize a Description string to a single logical line by:
    - Stripping leading/trailing whitespace.
    - Replacing all internal runs of whitespace (spaces, tabs, newlines) with single spaces.
    """
    return " ".join(value.split())


def normalize_descriptions(template: CommentedMap) -> None:
    """
    Ensure all Description fields are single-line strings, with no embedded
    newlines or irregular whitespace. This affects:
    - Top-level Description (if present).
    - Per-resource Properties.Description fields.
    """
    top_desc = template.get("Description")
    if isinstance(top_desc, str):
        template["Description"] = _normalize_description_value(top_desc)

    resources = template.get("Resources")
    if not isinstance(resources, CommentedMap):
        return

    for _, res in resources.items():
        if not isinstance(res, CommentedMap):
            continue
        props = res.get("Properties")
        if not isinstance(props, CommentedMap):
            continue
        desc = props.get("Description")
        if isinstance(desc, str):
            props["Description"] = _normalize_description_value(desc)


# ---------------------------------------------------------------------------
# Generate full conformance pack template
# ---------------------------------------------------------------------------


def generate_conformance_pack(
    rule_names: List[str],
    sot_yaml: CommentedMap,
    sot_index: Dict[str, CommentedMap],
) -> CommentedMap:
    resources = CommentedMap()

    for rule_name in rule_names:
        logical_id = derive_logical_id(rule_name)
        existing_resource = sot_index.get(rule_name)

        if logical_id in resources:
            logger.error(f"Duplicate logical ID generated: {logical_id}")
            sys.exit(1)

        if existing_resource is not None:
            mutate_resource_in_place(rule_name, existing_resource)
            resources[logical_id] = existing_resource
            logger.info(f"Included SOT-backed rule: {rule_name} -> {logical_id}")
        else:
            logger.info(
                f"No SOT entry found for rule '{rule_name}'; generating without "
                f"Description, InputParameters, or Scope."
            )
            new_resource = CommentedMap()
            new_resource["Type"] = "AWS::Config::ConfigRule"

            props = CommentedMap()
            props["ConfigRuleName"] = rule_name

            source_map = CommentedMap()
            source_map["Owner"] = "AWS"
            source_map["SourceIdentifier"] = derive_source_identifier_from_name(rule_name)
            props["Source"] = source_map
            props["InputParameters"] = CommentedMap()

            new_resource["Properties"] = props
            resources[logical_id] = new_resource

    template = CommentedMap()
    template["AWSTemplateFormatVersion"] = "2010-09-09"
    template["Description"] = (
        "Conformance Pack generated from curated list of AWS Config Managed Rules"
    )
    template["Resources"] = resources

    normalize_descriptions(template)
    return template
# ---------------------------------------------------------------------------
# main()
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Generate an AWS Config Conformance Pack from a list of managed rule "
            "names and a Source of Truth file, preserving YAML comments."
        )
    )
    parser.add_argument(
        "-t",
        "--truth-file",
        type=Path,
        default=Path("truth01.yml"),
        help="Source-of-truth YAML file (default: truth01.yml).",
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
        help="Output conformance pack YAML file (default: cpout01.yml).",
    )

    args = parser.parse_args()

    rule_names = load_rules_json(args.rules_json)
    sot_yaml = load_yaml(args.truth_file)
    sot_index = build_sot_index(sot_yaml)

    template = generate_conformance_pack(rule_names, sot_yaml, sot_index)

    try:
        with args.output.open("w", encoding="utf-8") as f:
            yaml_rt.dump(template, f)
    except OSError as e:
        logger.error(f"Failed to write output to {args.output}: {e}")
        sys.exit(1)

    logger.info(f"Conformance pack template written to {args.output}")


if __name__ == "__main__":
    main()