#!/usr/bin/env python3
"""
mba_csv.py — read-only MBA export of NIAID catalog parameters.

Does not write DynamoDB. Does not modify GROUP# bindings.
Uses bindingsNG.py catalog readers and description cleaning.

  python3 python/mba_csv.py --csv /tmp/all-profiles.csv --all-profiles --group 26y
  python3 python/mba_csv.py --csv /tmp/s3.csv --rule s3-lifecycle-policy-check --group 26y
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import bindingsNG as ng

NIAID_VERSION_KEYS = ("niaid_version", "baseline_version", "niaid_module_version")
MBA_CSV_COLUMNS = (
    "niaid_version",
    "config_rule",
    "source_identifier",
    "parameter_name",
    "required",
    "default_value",
    "data_type",
    "parameter_description",
    "rule_description",
    "group",
    "binding_value",
    "compat",
)


def resolve_niaid_version(
    profile: Optional[Dict[str, Any]],
    cli_override: Optional[str] = None,
) -> str:
    if profile:
        for key in NIAID_VERSION_KEYS:
            raw = profile.get(key)
            if raw is None:
                continue
            text = str(raw).strip()
            if text:
                return text
    if cli_override is not None and str(cli_override).strip():
        return str(cli_override).strip()
    return ""


def _csv_bool(value: bool) -> str:
    return "true" if value else "false"


def build_mba_rows(
    *,
    rule_id: str,
    group: str,
    profile: Optional[Dict[str, Any]],
    param_defs: List[Dict[str, Any]],
    binding_item: Optional[Dict[str, Any]],
    niaid_override: Optional[str] = None,
) -> List[Dict[str, str]]:
    bound = ng.existing_parameter_map(binding_item)
    sid = ""
    if profile:
        sid = str(profile.get("source_identifier") or "").strip()
    if not sid:
        sid = ng.derive_source_identifier(rule_id)
    rule_description = ng.choose_profile_description(
        None, (profile or {}).get("description")
    )
    version = resolve_niaid_version(profile, niaid_override)
    defs = [p for p in param_defs if p.get("parameter_name")]
    if not defs:
        return [
            {
                "niaid_version": version,
                "config_rule": rule_id,
                "source_identifier": sid,
                "parameter_name": "",
                "required": "",
                "default_value": "",
                "data_type": "",
                "parameter_description": "",
                "rule_description": rule_description or "",
                "group": group,
                "binding_value": "",
                "compat": "OK",
            }
        ]

    rows: List[Dict[str, str]] = []
    for param_def in defs:
        name = str(param_def.get("parameter_name") or "")
        required = ng.parameter_is_required(param_def)
        catalog_default = ng._stringify(param_def.get("default_value")) or ""
        real_default = "" if ng._is_placeholder(catalog_default) else catalog_default
        bound_value = bound.get(name) or ""
        if ng._is_placeholder(bound_value):
            bound_value = ""
        missing = required and not real_default and not bound_value
        rows.append(
            {
                "niaid_version": version,
                "config_rule": rule_id,
                "source_identifier": sid,
                "parameter_name": name,
                "required": _csv_bool(required),
                "default_value": catalog_default,
                "data_type": str(
                    param_def.get("data_type") or param_def.get("type") or "string"
                ),
                "parameter_description": str(param_def.get("description") or ""),
                "rule_description": rule_description or "",
                "group": group,
                "binding_value": bound_value,
                "compat": "MISSING_REQUIRED" if missing else "OK",
            }
        )
    return rows


def collect_rows(
    table,
    rule_id: str,
    *,
    group: str,
    binding: str,
    niaid_override: Optional[str],
) -> List[Dict[str, str]]:
    profile = ng.get_profile(table, rule_id)
    if not profile:
        ng.progress("skip", rule=rule_id, reason="no_profile", mode="csv")
        return build_mba_rows(
            rule_id=rule_id,
            group=group,
            profile=None,
            param_defs=[],
            binding_item=None,
            niaid_override=niaid_override,
        )
    return build_mba_rows(
        rule_id=rule_id,
        group=group,
        profile=profile,
        param_defs=ng.query_param_defs(table, rule_id),
        binding_item=ng.get_binding(table, rule_id, group, binding),
        niaid_override=niaid_override,
    )


def write_mba_csv(path: Path, rows: List[Dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(MBA_CSV_COLUMNS))
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in MBA_CSV_COLUMNS})
    ng.progress("csv", path=str(path), rows=len(rows))


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Read-only MBA CSV export of NIAID catalog parameters."
    )
    parser.add_argument("--csv", dest="csv_path", required=True, help="Output CSV path.")
    parser.add_argument("--rules-json", help="JSON array of ConfigRuleName strings.")
    parser.add_argument("--rule", help="Single kebab ConfigRuleName.")
    parser.add_argument(
        "--all-profiles",
        action="store_true",
        help="Export every RULE_PROFILE in the table.",
    )
    parser.add_argument("--group", required=True, help="Organizational group (read-only).")
    parser.add_argument("--binding", default=ng.DEFAULT_BINDING)
    parser.add_argument("--table", default=None)
    parser.add_argument("--region", default=ng.DEFAULT_REGION)
    parser.add_argument("--niaid-version", dest="niaid_version", default=None)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Accepted for compatibility. This script never writes DynamoDB.",
    )
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    ids, source, source_label = ng.select_rule_ids(args)
    table_name = args.table or __import__("os").environ.get(
        "CONFIG_RULE_CATALOG_TABLE", ng.DEFAULT_TABLE
    )
    ddb = ng.get_table(table_name, args.region)
    if source == "all-profiles":
        ids = ng.list_all_profile_ids(ddb)
    if args.limit and args.limit > 0:
        ids = ids[: args.limit]
    ng.progress("select", source=source, count=len(ids), file=source_label, mode="csv")
    rows: List[Dict[str, str]] = []
    for rule_id in ids:
        rows.extend(
            collect_rows(
                ddb,
                rule_id,
                group=args.group,
                binding=args.binding,
                niaid_override=args.niaid_version,
            )
        )
    write_mba_csv(Path(args.csv_path), rows)
    ng.progress("summary", binding_writes=0, csv_rows=len(rows), dry_run=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
