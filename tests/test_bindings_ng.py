#!/usr/bin/env python3
"""Unit tests for python/bindingsNG.py."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import boto3
import pytest
from moto import mock_aws

REPO_ROOT = Path(__file__).resolve().parents[1]
PYTHON_DIR = REPO_ROOT / "python"


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def bindingsNG():
    return _load_module("bindingsNG_ut", PYTHON_DIR / "bindingsNG.py")


TABLE_NAME = "y62db-config-rule-catalog"
REGION = "us-east-1"
GROUP = "26y"
BINDING = "default"

CFN_BODY = b"""
Parameters:
  targetTransitionDays:
    Type: String
    Default: "30"
  targetPrefix:
    Type: String
Resources:
  Rule:
    Type: AWS::Config::ConfigRule
    Properties:
      Source:
        Owner: AWS
        SourceIdentifier: S3_LIFECYCLE_POLICY_CHECK
      InputParameters:
        targetTransitionDays:
          Ref: targetTransitionDays
        targetPrefix:
          Ref: targetPrefix
"""


def _http_ok(_url: str) -> bytes:
    return CFN_BODY


def _http_404(url: str) -> bytes:
    import urllib.error

    raise urllib.error.HTTPError(url, 404, "Not Found", hdrs=None, fp=None)


@pytest.fixture
def ddb_table():
    with mock_aws():
        client = boto3.client("dynamodb", region_name=REGION)
        client.create_table(
            TableName=TABLE_NAME,
            KeySchema=[
                {"AttributeName": "pk", "KeyType": "HASH"},
                {"AttributeName": "sk", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "pk", "AttributeType": "S"},
                {"AttributeName": "sk", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        table = boto3.resource("dynamodb", region_name=REGION).Table(TABLE_NAME)
        yield table


def put_profile(table, rule_id: str, source_identifier: Optional[str] = None) -> None:
    sid = source_identifier or rule_id.replace("-", "_").upper()
    table.put_item(
        Item={
            "pk": f"RULE#{rule_id}",
            "sk": f"PROFILE#{rule_id}",
            "entity_type": "RULE_PROFILE",
            "rule_id": rule_id,
            "source_identifier": sid,
            "managed_rule": True,
        }
    )


def put_paramdef(
    table,
    rule_id: str,
    name: str,
    *,
    required: bool,
    default_value: str = "",
) -> None:
    table.put_item(
        Item={
            "pk": f"RULE#{rule_id}",
            "sk": f"PARAMDEF#{name}",
            "entity_type": "PARAMETER_DEF",
            "rule_id": rule_id,
            "parameter_name": name,
            "data_type": "string",
            "required": required,
            "default_value": default_value,
        }
    )


def extract_cpgng_binding_values(item: Dict[str, Any]) -> Dict[str, Any]:
    payload = dict(item.get("payload") or {})
    binding_payload = payload.get("parameter_values") or payload
    if isinstance(binding_payload, dict):
        binding_payload = dict(binding_payload)
        for meta in ("status", "version", "scope_values", "created_by"):
            binding_payload.pop(meta, None)
    return binding_payload


def run_cli(bindingsNG, table, extra: List[str], http_get=_http_ok):
    args = bindingsNG.parse_args(extra)
    return bindingsNG.run(args, table=table, http_get=http_get)


def test_missing_profile_writes_nothing(bindingsNG, ddb_table):
    put_profile(ddb_table, "s3-lifecycle-policy-check")
    put_paramdef(
        ddb_table,
        "s3-lifecycle-policy-check",
        "targetTransitionDays",
        required=True,
        default_value="30",
    )
    rc = run_cli(
        bindingsNG,
        ddb_table,
        [
            "--rule",
            "unknown-rule",
            "--group",
            GROUP,
            "--table",
            TABLE_NAME,
            "--region",
            REGION,
        ],
    )
    assert rc == 0
    scan = ddb_table.scan()
    assert all(
        not (i.get("sk") or "").startswith("GROUP#") for i in scan.get("Items", [])
    )


def test_fail_on_missing_profile_exit_2(bindingsNG, ddb_table):
    rc = run_cli(
        bindingsNG,
        ddb_table,
        [
            "--rule",
            "unknown-rule",
            "--group",
            GROUP,
            "--fail-on-missing-profile",
            "--table",
            TABLE_NAME,
            "--region",
            REGION,
        ],
    )
    assert rc == 2


def test_required_without_value_no_write(bindingsNG, ddb_table):
    rule = "bedrock-data-source-encryption-enabled"
    put_profile(ddb_table, rule)
    put_paramdef(ddb_table, rule, "kmsKeyId", required=True, default_value="")
    rc = run_cli(
        bindingsNG,
        ddb_table,
        ["--rule", rule, "--group", GROUP, "--table", TABLE_NAME, "--region", REGION],
    )
    assert rc == 0
    got = ddb_table.get_item(
        Key={"pk": f"RULE#{rule}", "sk": f"GROUP#{GROUP}#BINDING#{BINDING}"}
    )
    assert "Item" not in got


def test_required_paramdef_default_creates_ready_binding(bindingsNG, ddb_table):
    rule = "s3-lifecycle-policy-check"
    put_profile(ddb_table, rule, "S3_LIFECYCLE_POLICY_CHECK")
    put_paramdef(
        ddb_table, rule, "targetTransitionDays", required=True, default_value="30"
    )
    rc = run_cli(
        bindingsNG,
        ddb_table,
        ["--rule", rule, "--group", GROUP, "--table", TABLE_NAME, "--region", REGION],
    )
    assert rc == 0
    got = ddb_table.get_item(
        Key={"pk": f"RULE#{rule}", "sk": f"GROUP#{GROUP}#BINDING#{BINDING}"}
    )
    item = got["Item"]
    payload = item["payload"]
    assert payload["status"] == "ACTIVE"
    assert int(payload["version"]) == 1
    assert payload["parameter_values"]["targetTransitionDays"] == "30"
    assert payload["targetTransitionDays"] == "30"
    for forbidden in ("input_parameters", "resolution", "logical_id"):
        assert forbidden not in payload
    assert item["entity_type"] == "RULE_BINDING"
    assert item["classification"] == "READY"
    extracted = extract_cpgng_binding_values(item)
    assert set(extracted) <= {"targetTransitionDays", "parameter_values"}
    assert extracted["targetTransitionDays"] == "30"


def test_identical_binding_is_noop(bindingsNG, ddb_table):
    rule = "s3-lifecycle-policy-check"
    put_profile(ddb_table, rule)
    put_paramdef(
        ddb_table, rule, "targetTransitionDays", required=True, default_value="30"
    )
    run_cli(
        bindingsNG,
        ddb_table,
        ["--rule", rule, "--group", GROUP, "--table", TABLE_NAME, "--region", REGION],
    )
    first = ddb_table.get_item(
        Key={"pk": f"RULE#{rule}", "sk": f"GROUP#{GROUP}#BINDING#{BINDING}"}
    )["Item"]
    run_cli(
        bindingsNG,
        ddb_table,
        ["--rule", rule, "--group", GROUP, "--table", TABLE_NAME, "--region", REGION],
    )
    second = ddb_table.get_item(
        Key={"pk": f"RULE#{rule}", "sk": f"GROUP#{GROUP}#BINDING#{BINDING}"}
    )["Item"]
    assert int(second["payload"]["version"]) == 1
    assert second["updated_at"] == first["updated_at"]


def test_changed_binding_bumps_version_keeps_created_at(bindingsNG, ddb_table):
    rule = "access-keys-rotated"
    put_profile(ddb_table, rule)
    put_paramdef(ddb_table, rule, "maxAccessKeyAge", required=True, default_value="90")
    ddb_table.put_item(
        Item={
            "pk": f"RULE#{rule}",
            "sk": f"GROUP#{GROUP}#BINDING#{BINDING}",
            "gsi1pk": f"GROUP#{GROUP}",
            "gsi1sk": f"RULE#{rule}#BINDING#{BINDING}",
            "created_at": "2020-01-01T00:00:00Z",
            "updated_at": "2020-01-01T00:00:00Z",
            "payload": {
                "status": "ACTIVE",
                "version": 1,
                "parameter_values": {"maxAccessKeyAge": "99999"},
                "maxAccessKeyAge": "99999",
            },
        }
    )
    rc = run_cli(
        bindingsNG,
        ddb_table,
        ["--rule", rule, "--group", GROUP, "--table", TABLE_NAME, "--region", REGION],
    )
    assert rc == 0
    item = ddb_table.get_item(
        Key={"pk": f"RULE#{rule}", "sk": f"GROUP#{GROUP}#BINDING#{BINDING}"}
    )["Item"]
    assert int(item["payload"]["version"]) == 2
    assert item["created_at"] == "2020-01-01T00:00:00Z"
    assert item["payload"]["parameter_values"]["maxAccessKeyAge"] == "90"


def test_placeholder_default_does_not_count(bindingsNG, ddb_table):
    rule = "s3-lifecycle-policy-check"
    put_profile(ddb_table, rule)
    put_paramdef(
        ddb_table, rule, "targetExpirationDays", required=True, default_value="99999"
    )
    rc = run_cli(
        bindingsNG,
        ddb_table,
        ["--rule", rule, "--group", GROUP, "--table", TABLE_NAME, "--region", REGION],
    )
    assert rc == 0
    got = ddb_table.get_item(
        Key={"pk": f"RULE#{rule}", "sk": f"GROUP#{GROUP}#BINDING#{BINDING}"}
    )
    assert "Item" not in got


def test_cfn_default_does_not_write_paramdef_or_profile(bindingsNG, ddb_table):
    rule = "s3-lifecycle-policy-check"
    put_profile(ddb_table, rule, "S3_LIFECYCLE_POLICY_CHECK")
    put_paramdef(ddb_table, rule, "targetPrefix", required=False, default_value="")
    rc = run_cli(
        bindingsNG,
        ddb_table,
        ["--rule", rule, "--group", GROUP, "--table", TABLE_NAME, "--region", REGION],
    )
    assert rc == 0
    profile = ddb_table.get_item(
        Key={"pk": f"RULE#{rule}", "sk": f"PROFILE#{rule}"}
    )["Item"]
    assert profile["entity_type"] == "RULE_PROFILE"
    param = ddb_table.get_item(
        Key={"pk": f"RULE#{rule}", "sk": "PARAMDEF#targetPrefix"}
    )["Item"]
    assert param["default_value"] == ""
    assert param["required"] is False
    binding = ddb_table.get_item(
        Key={"pk": f"RULE#{rule}", "sk": f"GROUP#{GROUP}#BINDING#{BINDING}"}
    )["Item"]
    assert "targetPrefix" not in (binding["payload"].get("parameter_values") or {})


def test_cfn_default_does_not_satisfy_required(bindingsNG, ddb_table):
    rule = "s3-lifecycle-policy-check"
    put_profile(ddb_table, rule, "S3_LIFECYCLE_POLICY_CHECK")
    put_paramdef(
        ddb_table, rule, "targetTransitionDays", required=True, default_value=""
    )
    rc = run_cli(
        bindingsNG,
        ddb_table,
        ["--rule", rule, "--group", GROUP, "--table", TABLE_NAME, "--region", REGION],
    )
    assert rc == 0
    got = ddb_table.get_item(
        Key={"pk": f"RULE#{rule}", "sk": f"GROUP#{GROUP}#BINDING#{BINDING}"}
    )
    assert "Item" not in got
    param = ddb_table.get_item(
        Key={"pk": f"RULE#{rule}", "sk": "PARAMDEF#targetTransitionDays"}
    )["Item"]
    assert param["default_value"] == ""


def test_dry_run_writes_nothing(bindingsNG, ddb_table):
    rule = "s3-lifecycle-policy-check"
    put_profile(ddb_table, rule)
    put_paramdef(
        ddb_table, rule, "targetTransitionDays", required=True, default_value="30"
    )
    rc = run_cli(
        bindingsNG,
        ddb_table,
        [
            "--rule",
            rule,
            "--group",
            GROUP,
            "--dry-run",
            "--table",
            TABLE_NAME,
            "--region",
            REGION,
        ],
    )
    assert rc == 0
    got = ddb_table.get_item(
        Key={"pk": f"RULE#{rule}", "sk": f"GROUP#{GROUP}#BINDING#{BINDING}"}
    )
    assert "Item" not in got


def test_rules_json_slice_and_skip_unknown(bindingsNG, ddb_table, tmp_path):
    rule = "s3-lifecycle-policy-check"
    put_profile(ddb_table, rule)
    put_paramdef(
        ddb_table, rule, "targetTransitionDays", required=True, default_value="30"
    )
    slice_path = tmp_path / "slice.json"
    slice_path.write_text(json.dumps([rule, "not-in-catalog"]), encoding="utf-8")
    rc = run_cli(
        bindingsNG,
        ddb_table,
        [
            "--rules-json",
            str(slice_path),
            "--group",
            GROUP,
            "--table",
            TABLE_NAME,
            "--region",
            REGION,
        ],
    )
    assert rc == 0
    assert "Item" in ddb_table.get_item(
        Key={"pk": f"RULE#{rule}", "sk": f"GROUP#{GROUP}#BINDING#{BINDING}"}
    )
    assert "Item" not in ddb_table.get_item(
        Key={
            "pk": "RULE#not-in-catalog",
            "sk": f"GROUP#{GROUP}#BINDING#{BINDING}",
        }
    )


def test_exactly_one_selector_required(bindingsNG):
    args = bindingsNG.parse_args(["--group", GROUP])
    with pytest.raises(SystemExit) as exc:
        bindingsNG.select_rule_ids(args)
    assert exc.value.code == 1
    both = bindingsNG.parse_args(["--group", GROUP, "--rule", "a", "--all-profiles"])
    with pytest.raises(SystemExit):
        bindingsNG.select_rule_ids(both)


def test_cfn_404_does_not_abort_ready_from_paramdef(bindingsNG, ddb_table):
    rule = "s3-lifecycle-policy-check"
    put_profile(ddb_table, rule)
    put_paramdef(
        ddb_table, rule, "targetTransitionDays", required=True, default_value="30"
    )
    rc = run_cli(
        bindingsNG,
        ddb_table,
        ["--rule", rule, "--group", GROUP, "--table", TABLE_NAME, "--region", REGION],
        http_get=_http_404,
    )
    assert rc == 0
    item = ddb_table.get_item(
        Key={"pk": f"RULE#{rule}", "sk": f"GROUP#{GROUP}#BINDING#{BINDING}"}
    )["Item"]
    assert item["payload"]["parameter_values"]["targetTransitionDays"] == "30"
    assert item["cfn_template_sha256"] == ""
