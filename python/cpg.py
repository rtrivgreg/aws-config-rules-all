import argparse
import json
import logging
import math
import sys
from pathlib import Path
from typing import Dict, List, Optional

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger(__name__)

yaml_rt = YAML(typ="rt")
yaml_rt.indent(mapping=2, sequence=4, offset=2)
yaml_rt.width = 4096
yaml_rt.representer.ignore_aliases = lambda x: True


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


def load_yaml(path: Path) -> CommentedMap:
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


def kebab_to_pascal(name: str) -> str:
    return "".join(p.capitalize() for p in name.split("-") if p)


def derive_logical_id(config_rule_name: str) -> str:
    return kebab_to_pascal(config_rule_name) + "Rule"


def derive_source_identifier_from_name(config_rule_name: str) -> str:
    return config_rule_name.replace("-", "_").upper()


def build_sot_index(sot: CommentedMap) -> Dict[str, CommentedMap]:
    resources = sot.get("Resources")
    if resources is None:
        return {}

    if not isinstance(resources, CommentedMap):
        logger.warning("SOT has Resources, but it is not a mapping; SOT will be ignored.")
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
        if name in index:
            logger.warning(f"Duplicate ConfigRuleName in SOT; keeping first and skipping: {name}")
            continue
        index[name] = res

    return index


def resolve_source_identifier(rule_name: str, resource: Optional[CommentedMap]) -> str:
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


def ensure_input_parameters_map(resource: CommentedMap) -> None:
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


def mutate_resource_in_place(rule_name: str, resource: CommentedMap) -> None:
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


def _normalize_description_value(value: str) -> str:
    return " ".join(value.split())


def normalize_descriptions(template: CommentedMap) -> None:
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


def build_pack_template(rule_names: List[str], sot_index: Dict[str, CommentedMap]) -> CommentedMap:
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
                f"No SOT entry found for rule '{rule_name}'; generating without Description, InputParameters, or Scope."
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
    template["Description"] = "Conformance Pack generated from curated list of AWS Config Managed Rules"
    template["Resources"] = resources

    normalize_descriptions(template)
    return template


def batch_rules(rule_names: List[str], batch_size: int = 30) -> List[List[str]]:
    return [rule_names[i:i + batch_size] for i in range(0, len(rule_names), batch_size)]


def output_path_for_part(output_path: Path, part_num: int) -> Path:
    return output_path.with_name(f"{output_path.stem}-part{part_num:02d}{output_path.suffix}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate AWS Config Conformance Pack YAML files from a list of managed rule names and a Source of Truth file, preserving YAML comments."
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
        help="Output conformance pack YAML basename (default: cpout01.yml).",
    )

    args = parser.parse_args()

    rule_names = load_rules_json(args.rules_json)
    sot_yaml = load_yaml(args.truth_file)
    sot_index = build_sot_index(sot_yaml)

    packs = batch_rules(rule_names, 30)
    logger.info(f"Total requested rules: {len(rule_names)}")
    logger.info(f"Total packs to generate: {len(packs)}")

    for idx, pack_rules in enumerate(packs, start=1):
        out_path = output_path_for_part(args.output, idx)
        logger.info(f"Generating pack {idx}/{len(packs)} with {len(pack_rules)} rules -> {out_path}")

        template = build_pack_template(pack_rules, sot_index)

        try:
            with out_path.open("w", encoding="utf-8") as f:
                yaml_rt.dump(template, f)
        except OSError as e:
            logger.error(f"Failed to write output to {out_path}: {e}")
            sys.exit(1)

        logger.info(f"Wrote {out_path}")

    logger.info(f"Generated {len(packs)} conformance pack file(s) successfully.")


if __name__ == "__main__":
    main()
