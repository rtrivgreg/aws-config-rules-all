#!/usr/bin/env python3
"""
bindingsNG.py — organizational RULE_BINDING writer, plus an explicit NIAID
baseline refresh path.

Default mode writes only RULE_BINDING items so cpgNG can overlay group-specific
parameter values on the NIAID baseline. It does not fabricate packs, deploy
Config resources, or mutate baseline rows.

--update mode reconciles NIAID RULE_PROFILE and PARAMETER_DEF rows from the
AWS managed-rule CloudFormation template. It never writes GROUP# bindings.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import boto3
from botocore.exceptions import BotoCoreError, ClientError

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore


DEFAULT_TABLE = "y62db-config-rule-catalog"
DEFAULT_BINDING = "default"
DEFAULT_REGION = "us-east-1"
DEFAULT_GROUP_REQUIRED = True
PLACEHOLDER_DEFAULTS = frozenset({"99999"})
CFN_TEMPLATE_URL = (
    "https://s3.amazonaws.com/aws-configservice-us-east-1/"
    "cloudformation-templates-for-managed-rules/{identifier}.template"
)
FORBIDDEN_PAYLOAD_KEYS = frozenset(
    {
        "input_parameters",
        "resolution",
        "logical_id",
        "source_identifier",
        "cfn_template_url",
        "missing_required",
    }
)
PAYLOAD_META_KEYS = frozenset({"status", "version", "scope_values", "created_by"})
BASELINE_SK_PREFIXES = ("PROFILE#", "PARAMDEF#")
CFN_NON_INPUT_PARAMS = frozenset({"ConfigRuleName", "MaximumExecutionFrequency"})
INVENTORY_RE = re.compile(
    r"Input parameters for the .+? rule\.\s*",
    re.IGNORECASE | re.DOTALL,
)
PARAM_INVENTORY_LEAD_RE = re.compile(
    r"^[A-Za-z_][A-Za-z0-9_]*\([^)]*\)\s*,\s*[A-Za-z_][A-Za-z0-9_]*\("
)


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def progress(kind: str, **fields: Any) -> None:
    parts = [f"[bindingsNG] {kind:<8}"]
    for key, value in fields.items():
        parts.append(f"{key}={value}")
    sys.stderr.write(" ".join(parts) + "\n")


def load_rules_json(path: Path) -> List[str]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Failed to read rules JSON {path}: {exc}", file=sys.stderr)
        sys.exit(1)
    if not isinstance(data, list):
        print("Rules JSON must contain a JSON array of strings.", file=sys.stderr)
        sys.exit(1)
    rules: List[str] = []
    for item in data:
        if not isinstance(item, str):
            print("All items in the rules JSON array must be strings.", file=sys.stderr)
            sys.exit(1)
        name = item.strip()
        if name:
            rules.append(name)
    if not rules:
        print("No valid rule names found in rules JSON.", file=sys.stderr)
        sys.exit(1)
    return rules


def derive_source_identifier(rule_id: str) -> str:
    return rule_id.replace("-", "_").upper()


def _pk(rule_id: str) -> str:
    return f"RULE#{rule_id}"


def _profile_sk(rule_id: str) -> str:
    return f"PROFILE#{rule_id}"


def _paramdef_sk(name: str) -> str:
    return f"PARAMDEF#{name}"


def _binding_sk(group: str, binding: str) -> str:
    return f"GROUP#{group}#BINDING#{binding}"


def _gsi1pk(group: str) -> str:
    return f"GROUP#{group}"


def _gsi1sk(rule_id: str, binding: str) -> str:
    return f"RULE#{rule_id}#BINDING#{binding}"


def get_table(table_name: str, region: Optional[str]):
    kwargs: Dict[str, Any] = {}
    if region:
        kwargs["region_name"] = region
    return boto3.resource("dynamodb", **kwargs).Table(table_name)


def _truthy_flag(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value == 1
    if isinstance(value, str):
        return value.strip().lower() in {"true", "yes", "1", "required"}
    return False


def parameter_is_required(param_def: Dict[str, Any]) -> bool:
    if "required" in param_def:
        return _truthy_flag(param_def.get("required"))
    if "is_required" in param_def:
        return _truthy_flag(param_def.get("is_required"))
    return False


def _stringify(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value)
    if text == "":
        return None
    return text


def _is_placeholder(value: Optional[str]) -> bool:
    return value is not None and value in PLACEHOLDER_DEFAULTS


def get_profile(table, rule_id: str) -> Optional[Dict[str, Any]]:
    try:
        resp = table.get_item(Key={"pk": _pk(rule_id), "sk": _profile_sk(rule_id)})
    except (ClientError, BotoCoreError) as exc:
        print(f"DynamoDB error reading profile for '{rule_id}': {exc}", file=sys.stderr)
        sys.exit(1)
    return resp.get("Item")


def query_param_defs(table, rule_id: str) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    kwargs: Dict[str, Any] = {
        "KeyConditionExpression": "pk = :pk AND begins_with(sk, :prefix)",
        "ExpressionAttributeValues": {
            ":pk": _pk(rule_id),
            ":prefix": "PARAMDEF#",
        },
    }
    try:
        while True:
            resp = table.query(**kwargs)
            items.extend(resp.get("Items") or [])
            last = resp.get("LastEvaluatedKey")
            if not last:
                break
            kwargs["ExclusiveStartKey"] = last
    except (ClientError, BotoCoreError) as exc:
        print(f"DynamoDB error reading PARAMDEF for '{rule_id}': {exc}", file=sys.stderr)
        sys.exit(1)
    return items


def get_binding(table, rule_id: str, group: str, binding: str) -> Optional[Dict[str, Any]]:
    try:
        resp = table.get_item(
            Key={"pk": _pk(rule_id), "sk": _binding_sk(group, binding)}
        )
    except (ClientError, BotoCoreError) as exc:
        print(f"DynamoDB error reading binding for '{rule_id}': {exc}", file=sys.stderr)
        sys.exit(1)
    return resp.get("Item")


def list_all_profile_ids(table) -> List[str]:
    ids: List[str] = []
    kwargs: Dict[str, Any] = {"ProjectionExpression": "pk, sk"}
    try:
        while True:
            resp = table.scan(**kwargs)
            for item in resp.get("Items") or []:
                pk = item.get("pk") or ""
                sk = item.get("sk") or ""
                if pk.startswith("RULE#") and sk.startswith("PROFILE#"):
                    ids.append(pk.split("RULE#", 1)[1])
            last = resp.get("LastEvaluatedKey")
            if not last:
                break
            kwargs["ExclusiveStartKey"] = last
    except (ClientError, BotoCoreError) as exc:
        print(f"DynamoDB error scanning profiles: {exc}", file=sys.stderr)
        sys.exit(1)
    ids.sort()
    return ids


def fetch_cfn_template(
    source_identifier: str,
    opener=None,
) -> Tuple[Optional[str], Optional[str], Optional[bytes], str]:
    """Return (url, sha256_hex, body, status_label)."""
    url = CFN_TEMPLATE_URL.format(identifier=source_identifier)
    fetch = opener or _default_http_get
    try:
        body = fetch(url)
    except urllib.error.HTTPError as exc:
        return url, None, None, str(exc.code)
    except Exception as exc:  # noqa: BLE001 — network/parse isolation
        return url, None, None, type(exc).__name__
    digest = hashlib.sha256(body).hexdigest()
    return url, digest, body, "200"


def _default_http_get(url: str) -> bytes:
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=20) as resp:
        return resp.read()


def _load_cfn_doc(body: Optional[bytes]) -> Optional[Dict[str, Any]]:
    if not body:
        return None
    text = body.decode("utf-8", errors="replace")
    doc: Any = None
    if yaml is not None:
        try:
            doc = yaml.safe_load(text)
        except Exception:  # noqa: BLE001
            doc = None
    if doc is None:
        try:
            doc = json.loads(text)
        except Exception:  # noqa: BLE001
            return None
    if not isinstance(doc, dict):
        return None
    return doc


def parse_cfn_input_parameter_defaults(body: Optional[bytes]) -> Dict[str, str]:
    """Map Config InputParameters names -> CFN Default, informational only."""
    doc = _load_cfn_doc(body)
    if not doc:
        return {}

    parameters = doc.get("Parameters") or {}
    if not isinstance(parameters, dict):
        parameters = {}

    input_names: List[str] = []
    resources = doc.get("Resources") or {}
    if isinstance(resources, dict):
        for res in resources.values():
            if not isinstance(res, dict):
                continue
            if res.get("Type") != "AWS::Config::ConfigRule":
                continue
            props = res.get("Properties") or {}
            ip = props.get("InputParameters") if isinstance(props, dict) else None
            if isinstance(ip, dict):
                input_names.extend(str(k) for k in ip.keys())

    defaults: Dict[str, str] = {}
    names = input_names or [str(k) for k in parameters.keys()]
    for name in names:
        spec = parameters.get(name) or _param_spec_ci(parameters, name)
        if not isinstance(spec, dict):
            continue
        default = spec.get("Default")
        text_default = _stringify(default)
        if text_default is not None:
            defaults[name] = text_default
    return defaults


def _param_spec_ci(parameters: Dict[str, Any], name: str) -> Optional[Dict[str, Any]]:
    lower = name.lower()
    for key, spec in parameters.items():
        if str(key).lower() == lower and isinstance(spec, dict):
            return spec
    return None


def _plain_string(value: Any) -> Optional[str]:
    if isinstance(value, str):
        text = value.strip()
        return text or None
    return None


def parse_cfn_managed_baseline(body: Optional[bytes]) -> Optional[Dict[str, Any]]:
    """Parse managed-rule CFN into NIAID PROFILE/PARAMDEF inputs.

    required is True iff the Parameters entry has no Default key.
    Empty Default values are not treated as catalog defaults.
    """
    doc = _load_cfn_doc(body)
    if not doc:
        return None

    parameters = doc.get("Parameters") or {}
    if not isinstance(parameters, dict):
        parameters = {}

    description: Optional[str] = None
    source_identifier: Optional[str] = None
    input_names: List[str] = []
    resources = doc.get("Resources") or {}
    if isinstance(resources, dict):
        for res in resources.values():
            if not isinstance(res, dict):
                continue
            if res.get("Type") != "AWS::Config::ConfigRule":
                continue
            props = res.get("Properties") or {}
            if not isinstance(props, dict):
                continue
            if description is None:
                description = _plain_string(props.get("Description"))
            source = props.get("Source") or {}
            if isinstance(source, dict) and source_identifier is None:
                source_identifier = _plain_string(source.get("SourceIdentifier"))
            ip = props.get("InputParameters")
            if isinstance(ip, dict):
                for key in ip.keys():
                    name = str(key)
                    if name not in input_names:
                        input_names.append(name)

    specs: Dict[str, Dict[str, Any]] = {}
    for name in input_names:
        raw = parameters.get(name)
        if not isinstance(raw, dict):
            raw = _param_spec_ci(parameters, name) or {}
        has_default = isinstance(raw, dict) and "Default" in raw
        default_text = _stringify(raw.get("Default")) if has_default else None
        specs[name] = {
            "name": name,
            "has_default": has_default,
            "required": not has_default,
            "default": default_text,
            "description": _plain_string(raw.get("Description")) if raw else None,
            "type": str(raw.get("Type") or "String") if raw else "String",
        }

    return {
        "description": description,
        "source_identifier": source_identifier,
        "input_parameters": input_names,
        "parameters": specs,
    }


def looks_like_param_inventory(text: str) -> bool:
    if not text:
        return False
    if INVENTORY_RE.search(text):
        return True
    return bool(PARAM_INVENTORY_LEAD_RE.match(text.strip()))


def strip_inventory_prefix(text: str) -> str:
    """Drop prepended 'name(value), ... Input parameters for the X rule.' lists."""
    if not text:
        return ""
    cleaned = text.strip()
    match = INVENTORY_RE.search(cleaned)
    if match:
        rest = cleaned[match.end() :].strip()
        cleaned = rest
    if looks_like_param_inventory(cleaned):
        return ""
    return cleaned


def choose_profile_description(
    cfn_description: Optional[str],
    existing_description: Optional[str],
) -> str:
    official = strip_inventory_prefix(cfn_description or "")
    if official and not looks_like_param_inventory(official):
        return official
    existing = strip_inventory_prefix(existing_description or "")
    if existing and not looks_like_param_inventory(existing):
        return existing
    return official or existing or ""


def assert_baseline_sk(sk: str) -> None:
    text = sk or ""
    if text.startswith("GROUP#") or "#BINDING#" in text:
        raise AssertionError(f"refusing GROUP/binding write sk={text}")
    if not text.startswith(BASELINE_SK_PREFIXES):
        raise AssertionError(f"refusing non-allowlisted baseline sk={text}")


def _map_cfn_type(cfn_type: str) -> str:
    lowered = (cfn_type or "String").strip().lower()
    if lowered in {"number", "int", "integer"}:
        return "number"
    if lowered in {"comma-delimited-list", "list<string>", "list"}:
        return "string"
    return "string"


def existing_parameter_map(binding_item: Optional[Dict[str, Any]]) -> Dict[str, str]:
    if not binding_item:
        return {}
    payload = binding_item.get("payload") or {}
    if not isinstance(payload, dict):
        return {}
    nested = payload.get("parameter_values")
    source = nested if isinstance(nested, dict) else payload
    values: Dict[str, str] = {}
    for key, raw in source.items():
        if key in PAYLOAD_META_KEYS or key in FORBIDDEN_PAYLOAD_KEYS:
            continue
        if key == "parameter_values":
            continue
        text = _stringify(raw)
        if text is None:
            continue
        values[str(key)] = text
    return values


def resolve_value(
    name: str,
    param_def: Dict[str, Any],
    existing_values: Dict[str, str],
) -> Tuple[Optional[str], str]:
    bound = existing_values.get(name)
    if bound is not None and not _is_placeholder(bound):
        return bound, "binding_existing"
    required = parameter_is_required(param_def)
    catalog_default = _stringify(param_def.get("default_value"))
    if required and catalog_default is not None and not _is_placeholder(catalog_default):
        return catalog_default, "paramdef_default"
    return None, "unset"


def build_ready_payload(resolved: Dict[str, str], version: int) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "status": "ACTIVE",
        "version": version,
        "parameter_values": dict(resolved),
        "scope_values": {},
    }
    for name, value in resolved.items():
        payload[name] = value
    return payload


def values_equal(left: Dict[str, str], right: Dict[str, str]) -> bool:
    return left == right


def put_binding(
    table,
    *,
    rule_id: str,
    group: str,
    binding: str,
    payload: Dict[str, Any],
    extra_root: Dict[str, Any],
    created_at: str,
    expected_version: Optional[Any],
    create: bool,
) -> None:
    item = {
        "pk": _pk(rule_id),
        "sk": _binding_sk(group, binding),
        "gsi1pk": _gsi1pk(group),
        "gsi1sk": _gsi1sk(rule_id, binding),
        "entity_type": "RULE_BINDING",
        "rule_id": rule_id,
        "organizational_group": group,
        "binding_id": binding,
        "created_at": created_at,
        "updated_at": now_iso(),
        "payload": payload,
    }
    item.update(extra_root)
    try:
        if create:
            table.put_item(Item=item, ConditionExpression="attribute_not_exists(pk)")
        else:
            table.put_item(
                Item=item,
                ConditionExpression="attribute_exists(pk) AND payload.version = :expected_version",
                ExpressionAttributeValues={":expected_version": expected_version},
            )
    except ClientError as exc:
        code = (exc.response.get("Error") or {}).get("Code")
        if code == "ConditionalCheckFailedException":
            raise
        print(f"DynamoDB write failed for '{rule_id}': {exc}", file=sys.stderr)
        sys.exit(1)


def persist_baseline_item(table, item: Dict[str, Any], *, dry_run: bool) -> str:
    sk = str(item.get("sk") or "")
    assert_baseline_sk(sk)
    pk = str(item.get("pk") or "")
    if dry_run:
        progress("persist", rule=item.get("rule_id"), op="dry-run", pk=pk, sk=sk)
        return "dry-run"
    try:
        table.put_item(Item=item)
    except (ClientError, BotoCoreError) as exc:
        print(f"DynamoDB baseline write failed for {pk} {sk}: {exc}", file=sys.stderr)
        sys.exit(1)
    progress("persist", rule=item.get("rule_id"), op="upsert", pk=pk, sk=sk)
    return "upsert"


def delete_baseline_item(
    table,
    *,
    rule_id: str,
    pk: str,
    sk: str,
    dry_run: bool,
) -> str:
    assert_baseline_sk(sk)
    if dry_run:
        progress("persist", rule=rule_id, op="dry-run-delete", pk=pk, sk=sk)
        return "dry-run-delete"
    try:
        table.delete_item(Key={"pk": pk, "sk": sk})
    except (ClientError, BotoCoreError) as exc:
        print(f"DynamoDB baseline delete failed for {pk} {sk}: {exc}", file=sys.stderr)
        sys.exit(1)
    progress("persist", rule=rule_id, op="delete", pk=pk, sk=sk)
    return "delete"


def _paramdef_equivalent(existing: Dict[str, Any], desired: Dict[str, Any]) -> bool:
    keys = ("required", "default_value", "parameter_name", "entity_type", "data_type")
    for key in keys:
        if existing.get(key) != desired.get(key):
            return False
    desired_desc = desired.get("description")
    if desired_desc is not None and existing.get("description") != desired_desc:
        return False
    return True


def _profile_core_equivalent(existing: Dict[str, Any], desired: Dict[str, Any]) -> bool:
    for key in ("description", "source_identifier", "entity_type", "managed_rule"):
        if desired.get(key) is None:
            continue
        if existing.get(key) != desired.get(key):
            return False
    return True


def build_desired_paramdef(
    *,
    rule_id: str,
    spec: Dict[str, Any],
    existing: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    cfn_default = spec.get("default")
    existing_default = None
    if existing is not None:
        existing_default = existing.get("default_value")
        if existing_default is not None:
            existing_default = str(existing_default)

    if cfn_default is not None:
        default_value = str(cfn_default)
    elif existing_default not in (None,):
        default_value = existing_default
    else:
        default_value = ""

    item: Dict[str, Any] = {}
    if existing:
        item.update(existing)
    created_at = (existing or {}).get("created_at") or now_iso()
    item.update(
        {
            "pk": _pk(rule_id),
            "sk": _paramdef_sk(spec["name"]),
            "entity_type": "PARAMETER_DEF",
            "rule_id": rule_id,
            "parameter_name": spec["name"],
            "required": bool(spec["required"]),
            "default_value": default_value,
            "data_type": _map_cfn_type(str(spec.get("type") or "String")),
            "created_at": created_at,
            "updated_at": now_iso(),
        }
    )
    desc = spec.get("description")
    if desc:
        item["description"] = desc
    return item


def build_desired_profile(
    *,
    rule_id: str,
    parsed: Dict[str, Any],
    existing: Optional[Dict[str, Any]],
    source_identifier: str,
) -> Dict[str, Any]:
    item: Dict[str, Any] = {}
    if existing:
        item.update(existing)
    description = choose_profile_description(
        parsed.get("description"),
        (existing or {}).get("description"),
    )
    created_at = (existing or {}).get("created_at") or now_iso()
    item.update(
        {
            "pk": _pk(rule_id),
            "sk": _profile_sk(rule_id),
            "entity_type": "RULE_PROFILE",
            "rule_id": rule_id,
            "source_identifier": source_identifier,
            "description": description,
            "managed_rule": True,
            "created_at": created_at,
            "updated_at": now_iso(),
        }
    )
    return item


def report_group_compat(
    *,
    rule_id: str,
    group: str,
    binding: str,
    desired_paramdefs: List[Dict[str, Any]],
    binding_item: Optional[Dict[str, Any]],
) -> List[str]:
    bound = existing_parameter_map(binding_item)
    missing: List[str] = []
    for param_def in desired_paramdefs:
        name = str(param_def.get("parameter_name") or "")
        if not name or not parameter_is_required(param_def):
            continue
        catalog_default = _stringify(param_def.get("default_value"))
        has_real_default = (
            catalog_default is not None and not _is_placeholder(catalog_default)
        )
        bound_value = bound.get(name)
        has_bound = bound_value is not None and not _is_placeholder(bound_value)
        if not has_real_default and not has_bound:
            missing.append(name)
            progress(
                "compat",
                rule=rule_id,
                group=group,
                binding=binding,
                param=name,
                result="MISSING_REQUIRED",
            )
    if missing:
        progress(
            "compat",
            rule=rule_id,
            group=group,
            result="MISSING_REQUIRED",
            missing=",".join(missing),
        )
    else:
        progress("compat", rule=rule_id, group=group, result="OK")
    return missing


def process_update_rule(
    table,
    rule_id: str,
    *,
    group: str,
    binding: str,
    dry_run: bool,
    http_get=None,
) -> Tuple[str, Dict[str, int]]:
    """Reconcile PROFILE# / PARAMDEF# from CFN. Never writes GROUP# rows."""
    stats = {
        "profile_writes": 0,
        "paramdef_writes": 0,
        "paramdef_deletes": 0,
        "binding_writes": 0,
        "compat_missing_required": 0,
        "cfn_missing": 0,
    }
    profile = get_profile(table, rule_id)
    source_identifier = ""
    if profile:
        source_identifier = (profile.get("source_identifier") or "").strip()
    if not source_identifier:
        source_identifier = derive_source_identifier(rule_id)
    progress("profile", rule=rule_id, source_identifier=source_identifier, mode="update")

    url, sha256, body, cfn_status = fetch_cfn_template(source_identifier, opener=http_get)
    parsed = parse_cfn_managed_baseline(body) if cfn_status == "200" else None
    progress(
        "fetch-cfn",
        rule=rule_id,
        status=cfn_status,
        params=len((parsed or {}).get("input_parameters") or []),
        url=url or "",
    )
    if cfn_status != "200" or parsed is None:
        stats["cfn_missing"] = 1
        progress(
            "skip",
            rule=rule_id,
            reason="cfn_fetch_failed",
            status=cfn_status,
        )
        progress("persist", rule=rule_id, op="skip", reason="cfn_fetch_failed")
        return "skipped_cfn", stats

    if parsed.get("source_identifier"):
        source_identifier = str(parsed["source_identifier"])

    desired_profile = build_desired_profile(
        rule_id=rule_id,
        parsed=parsed,
        existing=profile,
        source_identifier=source_identifier,
    )
    if profile and _profile_core_equivalent(profile, desired_profile):
        progress(
            "persist",
            rule=rule_id,
            op="noop",
            pk=desired_profile["pk"],
            sk=desired_profile["sk"],
        )
    else:
        persist_baseline_item(table, desired_profile, dry_run=dry_run)
        stats["profile_writes"] = 0 if dry_run else 1

    existing_defs = query_param_defs(table, rule_id)
    existing_by_name: Dict[str, Dict[str, Any]] = {}
    for item in existing_defs:
        name = item.get("parameter_name")
        if not name:
            sk = str(item.get("sk") or "")
            if sk.startswith("PARAMDEF#"):
                name = sk.split("PARAMDEF#", 1)[1]
        if name:
            existing_by_name[str(name)] = item

    desired_paramdefs: List[Dict[str, Any]] = []
    wanted_names = set()
    for name in parsed.get("input_parameters") or []:
        if name in CFN_NON_INPUT_PARAMS:
            continue
        wanted_names.add(name)
        spec = (parsed.get("parameters") or {}).get(name) or {
            "name": name,
            "has_default": False,
            "required": True,
            "default": None,
            "description": None,
            "type": "String",
        }
        desired = build_desired_paramdef(
            rule_id=rule_id,
            spec=spec,
            existing=existing_by_name.get(name),
        )
        desired_paramdefs.append(desired)
        progress(
            "paramdef",
            rule=rule_id,
            param=name,
            required=str(desired["required"]).lower(),
            default=desired.get("default_value") if desired.get("default_value") else "-",
        )
        existing_item = existing_by_name.get(name)
        if existing_item and _paramdef_equivalent(existing_item, desired):
            progress(
                "persist",
                rule=rule_id,
                op="noop",
                pk=desired["pk"],
                sk=desired["sk"],
            )
            continue
        persist_baseline_item(table, desired, dry_run=dry_run)
        if not dry_run:
            stats["paramdef_writes"] += 1

    for name, existing_item in existing_by_name.items():
        if name in wanted_names:
            continue
        sk = str(existing_item.get("sk") or _paramdef_sk(name))
        delete_baseline_item(
            table,
            rule_id=rule_id,
            pk=_pk(rule_id),
            sk=sk,
            dry_run=dry_run,
        )
        if not dry_run:
            stats["paramdef_deletes"] += 1

    binding_item = get_binding(table, rule_id, group, binding)
    missing = report_group_compat(
        rule_id=rule_id,
        group=group,
        binding=binding,
        desired_paramdefs=desired_paramdefs,
        binding_item=binding_item,
    )
    stats["compat_missing_required"] = len(missing)
    progress(
        "summary-rule",
        rule=rule_id,
        profile_writes=stats["profile_writes"],
        paramdef_writes=stats["paramdef_writes"],
        paramdef_deletes=stats["paramdef_deletes"],
        binding_writes=stats["binding_writes"],
        sha256=sha256 or "",
    )
    if dry_run:
        return "ready_dry_run", stats
    if (
        stats["profile_writes"] == 0
        and stats["paramdef_writes"] == 0
        and stats["paramdef_deletes"] == 0
    ):
        return "noop", stats
    return "ready_written", stats


def process_rule(
    table,
    rule_id: str,
    *,
    group: str,
    binding: str,
    dry_run: bool,
    http_get=None,
) -> Tuple[str, bool]:
    """Return (outcome token, cfn_template_missing)."""
    profile = get_profile(table, rule_id)
    if not profile:
        progress("skip", rule=rule_id, reason="no_profile")
        return "skipped_no_profile", False

    source_identifier = (profile.get("source_identifier") or "").strip() or (
        derive_source_identifier(rule_id)
    )
    progress("profile", rule=rule_id, source_identifier=source_identifier)

    param_defs = query_param_defs(table, rule_id)
    existing_item = get_binding(table, rule_id, group, binding)
    existing_values = existing_parameter_map(existing_item)

    url, sha256, body, cfn_status = fetch_cfn_template(source_identifier, opener=http_get)
    cfn_defaults = parse_cfn_input_parameter_defaults(body)
    progress(
        "fetch-cfn",
        rule=rule_id,
        status=cfn_status,
        params=len(cfn_defaults),
    )
    cfn_missing = cfn_status != "200"

    resolved: Dict[str, str] = {}
    missing_required: List[str] = []
    for param_def in param_defs:
        name = param_def.get("parameter_name")
        if not name:
            continue
        name = str(name)
        value, source = resolve_value(name, param_def, existing_values)
        progress(
            "acquire",
            rule=rule_id,
            param=name,
            value=value if value is not None else "-",
            source=source,
        )
        if name in cfn_defaults:
            progress(
                "cfn-info",
                rule=rule_id,
                param=name,
                cfn_default=cfn_defaults[name],
            )
        if value is not None:
            resolved[name] = value
        elif parameter_is_required(param_def):
            missing_required.append(name)

    if missing_required:
        progress(
            "classify",
            rule=rule_id,
            result="BLOCKED_MISSING_REQUIRED",
            missing=",".join(missing_required),
        )
        progress("persist", rule=rule_id, op="skip", reason="missing_required")
        return "blocked_missing_required", cfn_missing

    progress("classify", rule=rule_id, result="READY", missing_required="none")

    extra_root = {
        "resolution_method": "cfn_managed_template",
        "classification": "READY",
        "cfn_template_url": url or "",
        "cfn_template_sha256": sha256 or "",
    }

    if dry_run:
        progress(
            "persist",
            rule=rule_id,
            op="dry-run",
            pk=_pk(rule_id),
            sk=_binding_sk(group, binding),
        )
        return "ready_dry_run", cfn_missing

    if existing_item:
        old_payload = existing_item.get("payload") or {}
        old_values = existing_parameter_map(existing_item)
        if values_equal(old_values, resolved) and old_payload.get("status") == "ACTIVE":
            progress(
                "persist",
                rule=rule_id,
                op="noop",
                pk=_pk(rule_id),
                sk=_binding_sk(group, binding),
            )
            return "noop", cfn_missing
        old_version = old_payload.get("version", 1)
        try:
            old_version_n = int(old_version)
        except (TypeError, ValueError):
            old_version_n = 1
        new_version = old_version_n + 1
        payload = build_ready_payload(resolved, new_version)
        created_at = existing_item.get("created_at") or now_iso()
        try:
            put_binding(
                table,
                rule_id=rule_id,
                group=group,
                binding=binding,
                payload=payload,
                extra_root=extra_root,
                created_at=created_at,
                expected_version=old_payload.get("version"),
                create=False,
            )
        except ClientError:
            latest = get_binding(table, rule_id, group, binding)
            if not latest:
                print(f"Binding disappeared during update of '{rule_id}'", file=sys.stderr)
                sys.exit(1)
            if existing_parameter_map(latest) == resolved:
                progress(
                    "persist",
                    rule=rule_id,
                    op="noop",
                    pk=_pk(rule_id),
                    sk=_binding_sk(group, binding),
                )
                return "noop", cfn_missing
            print(
                f"Optimistic lock failed for '{rule_id}'; refetch and retry later.",
                file=sys.stderr,
            )
            sys.exit(1)
        progress(
            "persist",
            rule=rule_id,
            op="update",
            pk=_pk(rule_id),
            sk=_binding_sk(group, binding),
            version=new_version,
        )
        return "ready_written", cfn_missing

    payload = build_ready_payload(resolved, 1)
    try:
        put_binding(
            table,
            rule_id=rule_id,
            group=group,
            binding=binding,
            payload=payload,
            extra_root=extra_root,
            created_at=now_iso(),
            expected_version=None,
            create=True,
        )
    except ClientError:
        print(f"Create conflict for '{rule_id}'", file=sys.stderr)
        sys.exit(1)
    progress(
        "persist",
        rule=rule_id,
        op="create",
        pk=_pk(rule_id),
        sk=_binding_sk(group, binding),
        version=1,
    )
    return "ready_written", cfn_missing


def select_rule_ids(args) -> Tuple[List[str], str, str]:
    chosen = [bool(args.rules_json), bool(args.rule), bool(args.all_profiles)]
    if sum(chosen) != 1:
        print(
            "Specify exactly one of --rules-json, --rule, or --all-profiles.",
            file=sys.stderr,
        )
        sys.exit(1)
    if args.rules_json:
        ids = load_rules_json(Path(args.rules_json))
        return ids, "rules-json", str(args.rules_json)
    if args.rule:
        return [args.rule.strip()], "rule", args.rule.strip()
    return [], "all-profiles", "*"


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Default: write organizational RULE_BINDING rows. "
            "--update: reconcile NIAID PROFILE# / PARAMDEF# from the AWS "
            "managed-rule CloudFormation template and never write GROUP# bindings."
        )
    )
    parser.add_argument("--rules-json", help="JSON array of ConfigRuleName strings.")
    parser.add_argument("--rule", help="Single kebab ConfigRuleName.")
    parser.add_argument(
        "--all-profiles",
        action="store_true",
        help="Process every RULE_PROFILE in the table.",
    )
    parser.add_argument(
        "--group",
        required=True,
        help=(
            "Organizational group. Default mode writes GROUP#{group} bindings. "
            "--update uses this group only for a read-only compatibility report."
        ),
    )
    parser.add_argument(
        "--binding",
        default=DEFAULT_BINDING,
        help=f"Binding id (default: {DEFAULT_BINDING}).",
    )
    parser.add_argument(
        "--table",
        default=None,
        help=f"DynamoDB table (default: env CONFIG_RULE_CATALOG_TABLE or {DEFAULT_TABLE}).",
    )
    parser.add_argument(
        "--region",
        default=DEFAULT_REGION,
        help=f"AWS region (default: {DEFAULT_REGION}).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute and print progress; write nothing.",
    )
    parser.add_argument(
        "--update",
        action="store_true",
        help=(
            "Reconcile NIAID RULE_PROFILE and PARAMETER_DEF from the managed-rule "
            "CFN template. Never writes GROUP# bindings."
        ),
    )
    parser.add_argument(
        "--fail-on-missing-profile",
        action="store_true",
        help="Exit 2 if any selected rule has no RULE_PROFILE.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Process only the first N selected rule ids.",
    )
    return parser.parse_args(argv)


def run(
    args: argparse.Namespace,
    *,
    table=None,
    http_get=None,
) -> int:
    table_name = args.table or __import__("os").environ.get(
        "CONFIG_RULE_CATALOG_TABLE", DEFAULT_TABLE
    )
    ids, source, source_label = select_rule_ids(args)
    ddb = table if table is not None else get_table(table_name, args.region)
    if source == "all-profiles":
        ids = list_all_profile_ids(ddb)
    if args.limit and args.limit > 0:
        ids = ids[: args.limit]
    progress(
        "select",
        source=source,
        count=len(ids),
        file=source_label,
        mode="update" if args.update else "binding",
    )

    if args.update:
        counts = {
            "ready_written": 0,
            "ready_dry_run": 0,
            "noop": 0,
            "skipped_cfn": 0,
            "skipped_no_profile": 0,
            "cfn_missing": 0,
            "profile_writes": 0,
            "paramdef_writes": 0,
            "paramdef_deletes": 0,
            "binding_writes": 0,
            "compat_missing_required": 0,
        }
        for rule_id in ids:
            outcome, stats = process_update_rule(
                ddb,
                rule_id,
                group=args.group,
                binding=args.binding,
                dry_run=args.dry_run,
                http_get=http_get,
            )
            counts[outcome] = counts.get(outcome, 0) + 1
            for key in (
                "profile_writes",
                "paramdef_writes",
                "paramdef_deletes",
                "binding_writes",
                "compat_missing_required",
                "cfn_missing",
            ):
                counts[key] = counts.get(key, 0) + int(stats.get(key, 0))
        if counts["binding_writes"] != 0:
            raise AssertionError(
                f"--update wrote GROUP bindings: binding_writes={counts['binding_writes']}"
            )
        progress(
            "summary",
            ready_written=counts["ready_written"],
            noop=counts["noop"],
            skipped_cfn=counts["skipped_cfn"],
            profile_writes=counts["profile_writes"],
            paramdef_writes=counts["paramdef_writes"],
            paramdef_deletes=counts["paramdef_deletes"],
            binding_writes=counts["binding_writes"],
            compat_missing_required=counts["compat_missing_required"],
            cfn_missing=counts["cfn_missing"],
            dry_run=int(args.dry_run),
        )
        return 0

    counts = {
        "ready_written": 0,
        "ready_dry_run": 0,
        "noop": 0,
        "skipped_no_profile": 0,
        "blocked_missing_required": 0,
        "cfn_missing": 0,
    }
    for rule_id in ids:
        outcome, cfn_missed = process_rule(
            ddb,
            rule_id,
            group=args.group,
            binding=args.binding,
            dry_run=args.dry_run,
            http_get=http_get,
        )
        counts[outcome] = counts.get(outcome, 0) + 1
        if cfn_missed:
            counts["cfn_missing"] += 1

    progress(
        "summary",
        ready_written=counts["ready_written"],
        noop=counts["noop"],
        skipped_no_profile=counts["skipped_no_profile"],
        blocked_missing_required=counts["blocked_missing_required"],
        cfn_missing=counts["cfn_missing"],
        dry_run=int(args.dry_run),
    )
    if args.fail_on_missing_profile and counts["skipped_no_profile"]:
        return 2
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    try:
        args = parse_args(argv)
        return run(args)
    except SystemExit as exc:
        code = exc.code
        return int(code) if isinstance(code, int) else 1


if __name__ == "__main__":
    sys.exit(main())
