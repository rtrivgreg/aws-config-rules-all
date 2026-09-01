#!/usr/bin/env python3
"""Read-only semantic diff for NIAID/vendor rule catalogs.

Each side may be a local JSON file, an HTTP(S) JSON document, or an AWS
DynamoDB table. The program never writes to either source.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.parse
import urllib.request
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable


COMMON_KEYS = (
    "SourceIdentifier",
    "sourceIdentifier",
    "source_identifier",
    "RuleName",
    "ruleName",
    "rule_name",
    "id",
    "name",
)


class DiffError(RuntimeError):
    """A user-actionable input or comparison error."""


@dataclass(frozen=True)
class Change:
    key: str
    fields: dict[str, dict[str, Any]]


def json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral() else float(value)
    if isinstance(value, set):
        return sorted(value, key=str)
    raise TypeError(f"Cannot serialize {type(value).__name__}")


def load_json_bytes(raw: bytes, label: str) -> Any:
    try:
        return json.loads(raw.decode("utf-8"), parse_float=Decimal)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DiffError(f"{label} did not contain valid UTF-8 JSON: {exc}") from exc


def load_url(uri: str, timeout: float) -> Any:
    request = urllib.request.Request(
        uri,
        headers={"Accept": "application/json", "User-Agent": "niaid-diff/1.0"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return load_json_bytes(response.read(), uri)
    except Exception as exc:
        raise DiffError(f"Unable to read URL {uri}: {exc}") from exc


def load_dynamodb(uri: str, profile: str | None) -> list[dict[str, Any]]:
    try:
        import boto3  # type: ignore
    except ImportError as exc:
        raise DiffError(
            "DynamoDB input requires boto3: python -m pip install boto3"
        ) from exc

    parsed = urllib.parse.urlparse(uri)
    table_name = (parsed.netloc + parsed.path).strip("/")
    query = urllib.parse.parse_qs(parsed.query)
    region = query.get("region", [None])[0]
    uri_profile = query.get("profile", [None])[0]
    endpoint_url = query.get("endpoint_url", [None])[0]
    if not table_name:
        raise DiffError("DynamoDB URI must name a table: dynamodb://TABLE")

    session = boto3.Session(
        profile_name=uri_profile or profile,
        region_name=region,
    )
    table = session.resource("dynamodb", endpoint_url=endpoint_url).Table(table_name)
    items: list[dict[str, Any]] = []
    scan_args: dict[str, Any] = {}
    try:
        while True:
            page = table.scan(**scan_args)
            items.extend(page.get("Items", []))
            last_key = page.get("LastEvaluatedKey")
            if not last_key:
                break
            scan_args["ExclusiveStartKey"] = last_key
    except Exception as exc:
        raise DiffError(f"Unable to scan DynamoDB table {table_name}: {exc}") from exc
    return items


def load_source(spec: str, timeout: float, profile: str | None) -> Any:
    if spec.startswith("dynamodb://"):
        return load_dynamodb(spec, profile)
    if spec.startswith(("https://", "http://")):
        return load_url(spec, timeout)
    path = Path(spec).expanduser()
    try:
        return load_json_bytes(path.read_bytes(), str(path))
    except OSError as exc:
        raise DiffError(f"Unable to read local file {path}: {exc}") from exc


def extract_records(document: Any, items_path: str | None) -> list[dict[str, Any]]:
    current = document
    if items_path:
        for component in items_path.split("."):
            if not isinstance(current, dict) or component not in current:
                raise DiffError(f"Items path '{items_path}' was not found")
            current = current[component]
    elif isinstance(current, dict):
        for candidate in ("Items", "items", "Rules", "rules", "data"):
            if isinstance(current.get(candidate), list):
                current = current[candidate]
                break
        else:
            if current and all(isinstance(v, dict) for v in current.values()):
                current = [dict(v, __mapping_key__=k) for k, v in current.items()]

    if not isinstance(current, list) or not all(
        isinstance(value, dict) for value in current
    ):
        raise DiffError(
            "Expected a JSON list of objects (use --items-path for a nested list)"
        )
    return current


def choose_key(records: Iterable[dict[str, Any]], requested: str | None) -> str:
    records = list(records)
    if requested:
        return requested
    for candidate in COMMON_KEYS:
        if records and all(candidate in record for record in records):
            return candidate
    if records and all("__mapping_key__" in record for record in records):
        return "__mapping_key__"
    raise DiffError("Could not infer a stable record key; specify --key FIELD")


def canonical(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: canonical(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        normalized = [canonical(item) for item in value]
        return sorted(
            normalized,
            key=lambda item: json.dumps(
                item,
                sort_keys=True,
                default=json_default,
            ),
        )
    if isinstance(value, set):
        return canonical(list(value))
    return value


def index_records(
    records: list[dict[str, Any]],
    key_field: str,
    ignore: set[str],
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for number, record in enumerate(records, 1):
        if key_field not in record:
            raise DiffError(f"Record {number} has no key field '{key_field}'")
        key = str(record[key_field])
        if key in result:
            raise DiffError(f"Duplicate key '{key}' in field '{key_field}'")
        result[key] = canonical(
            {
                field: value
                for field, value in record.items()
                if field not in ignore and field != "__mapping_key__"
            }
        )
    return result


def compare(
    source: dict[str, dict[str, Any]],
    target: dict[str, dict[str, Any]],
) -> tuple[list[str], list[str], list[Change]]:
    source_keys = set(source)
    target_keys = set(target)
    missing = sorted(source_keys - target_keys)
    extra = sorted(target_keys - source_keys)
    changed: list[Change] = []
    for key in sorted(source_keys & target_keys):
        if source[key] == target[key]:
            continue
        fields: dict[str, dict[str, Any]] = {}
        for field in sorted(set(source[key]) | set(target[key])):
            left = source[key].get(field, "<MISSING>")
            right = target[key].get(field, "<MISSING>")
            if left != right:
                fields[field] = {"source": left, "target": right}
        changed.append(Change(key, fields))
    return missing, extra, changed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Read-only semantic diff of two JSON/DynamoDB rule catalogs."
    )
    parser.add_argument(
        "source",
        help="Authoritative local path, URL, or dynamodb://TABLE URI",
    )
    parser.add_argument(
        "target",
        help="Comparison local path, URL, or dynamodb://TABLE URI",
    )
    parser.add_argument(
        "--key",
        help="Stable field identifying each rule (auto-detected if omitted)",
    )
    parser.add_argument(
        "--items-path",
        help="Dot path to the record list, e.g. catalog.rules",
    )
    parser.add_argument(
        "--ignore-field",
        action="append",
        default=[],
        help="Field to ignore; repeatable",
    )
    parser.add_argument("--profile", help="Default AWS profile for DynamoDB inputs")
    parser.add_argument(
        "--timeout",
        type=float,
        default=30.0,
        help="Web timeout in seconds",
    )
    parser.add_argument("--format", choices=("text", "json"), default="text")
    parser.add_argument(
        "--output",
        help="Write report to this file instead of standard output",
    )
    return parser


def render_text(
    missing: list[str],
    extra: list[str],
    changed: list[Change],
) -> str:
    lines = [
        "NIAID catalog diff (read-only)",
        f"Missing from target / restore candidates: {len(missing)}",
        f"Only in target / review as additions:      {len(extra)}",
        f"Present in both but changed:               {len(changed)}",
    ]
    for heading, values in (
        ("MISSING FROM TARGET", missing),
        ("ONLY IN TARGET", extra),
    ):
        if values:
            lines.extend(("", heading))
            lines.extend(f"  {value}" for value in values)
    if changed:
        lines.extend(("", "CHANGED"))
        for change in changed:
            lines.append(f"  {change.key}")
            for field, values in change.fields.items():
                left = json.dumps(
                    values["source"],
                    default=json_default,
                    sort_keys=True,
                )
                right = json.dumps(
                    values["target"],
                    default=json_default,
                    sort_keys=True,
                )
                lines.append(f"    {field}: {left} -> {right}")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        left_records = extract_records(
            load_source(args.source, args.timeout, args.profile),
            args.items_path,
        )
        right_records = extract_records(
            load_source(args.target, args.timeout, args.profile),
            args.items_path,
        )
        key_field = choose_key(left_records + right_records, args.key)
        ignore = set(args.ignore_field)
        left = index_records(left_records, key_field, ignore)
        right = index_records(right_records, key_field, ignore)
        missing, extra, changed = compare(left, right)
        if args.format == "json":
            report = json.dumps(
                {
                    "read_only": True,
                    "key_field": key_field,
                    "summary": {
                        "missing_from_target": len(missing),
                        "only_in_target": len(extra),
                        "changed": len(changed),
                    },
                    "missing_from_target": missing,
                    "only_in_target": extra,
                    "changed": [
                        {"key": change.key, "fields": change.fields}
                        for change in changed
                    ],
                },
                indent=2,
                default=json_default,
                sort_keys=True,
            ) + "\n"
        else:
            report = render_text(missing, extra, changed)
        if args.output:
            Path(args.output).write_text(report, encoding="utf-8")
        else:
            sys.stdout.write(report)
        return 1 if missing or extra or changed else 0
    except DiffError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
