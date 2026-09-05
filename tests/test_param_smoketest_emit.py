#!/usr/bin/env python3
"""cpgNG / upackNG half of the parameter-shape smoketest."""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional
from unittest.mock import patch

import pytest
import yaml

from test_param_smoketest import (
    BINDING,
    GROUP,
    REGION,
    TABLE_NAME,
    _mini_pack,
    ddb_table,
    pack_yaml,
    put_paramdef,
    put_profile,
    seed_cfn_catalog,
    source_identifier,
    upackNG,
    cpgNG,
    group_items,
)

def _run_cpgNG(cpgNG, tmp_path: Path, rules: List[str], table, extra=None):
    rules_path = tmp_path / "rules.json"
    out_base = tmp_path / "pack.yml"
    rules_path.write_text(json.dumps(rules), encoding="utf-8")
    argv = [
        "cpgNG.py",
        "-r",
        str(rules_path),
        "-o",
        str(out_base),
        "--table",
        TABLE_NAME,
        "--region",
        REGION,
    ]
    if extra:
        argv.extend(extra)
    from unittest.mock import patch

    with patch.object(sys, "argv", argv), patch.object(
        cpgNG, "_get_dynamodb_table", return_value=table
    ):
        cpgNG.main()
    pack = tmp_path / "pack-part01.yml"
    sidecar = tmp_path / "pack-part01.csv"
    with pack.open(encoding="utf-8") as handle:
        doc = yaml.safe_load(handle)
    return doc, sidecar


def test_cpgNG_zero_param_rule_emits_empty_map(cpgNG, ddb_table, tmp_path):
    seed_cfn_catalog(ddb_table, ["s3-bucket-public-read-prohibited"])
    doc, sidecar = _run_cpgNG(cpgNG, tmp_path, ["s3-bucket-public-read-prohibited"], ddb_table)
    props = doc["Resources"]["S3BucketPublicReadProhibitedRule"]["Properties"]
    assert props["InputParameters"] == {}
    assert sidecar.is_file()


def test_cpgNG_optional_cfn_default_omitted_until_bound(cpgNG, ddb_table, tmp_path):
    seed_cfn_catalog(ddb_table, ["access-keys-rotated"])
    unbound, _ = _run_cpgNG(cpgNG, tmp_path, ["access-keys-rotated"], ddb_table)
    assert (
        unbound["Resources"]["AccessKeysRotatedRule"]["Properties"]["InputParameters"]
        == {}
    )
    ddb_table.put_item(
        Item={
            "pk": "RULE#access-keys-rotated",
            "sk": f"GROUP#{GROUP}#BINDING#{BINDING}",
            "payload": {
                "status": "ACTIVE",
                "version": 1,
                "parameter_values": {"maxAccessKeyAge": "30"},
                "maxAccessKeyAge": "30",
            },
        }
    )
    bound_dir = tmp_path / "bound"
    bound_dir.mkdir()
    bound, _ = _run_cpgNG(
        cpgNG,
        bound_dir,
        ["access-keys-rotated"],
        ddb_table,
        extra=["--group", GROUP],
    )
    assert bound["Resources"]["AccessKeysRotatedRule"]["Properties"]["InputParameters"] == {
        "maxAccessKeyAge": "30"
    }


def test_cpgNG_lifecycle_niaid_samples_and_csv_string(cpgNG, ddb_table, tmp_path):
    seed_cfn_catalog(ddb_table, ["s3-lifecycle-policy-check"])
    ddb_table.put_item(
        Item={
            "pk": "RULE#s3-lifecycle-policy-check",
            "sk": f"GROUP#{GROUP}#BINDING#{BINDING}",
            "payload": {
                "status": "ACTIVE",
                "version": 1,
                "parameter_values": {
                    "targetTransitionDays": "30",
                    "targetExpirationDays": "90",
                    "targetTransitionStorageClass": "STANDARD_IA",
                    "bucketNames": "alpha-bucket,beta-bucket",
                },
                "targetTransitionDays": "30",
                "targetExpirationDays": "90",
                "targetTransitionStorageClass": "STANDARD_IA",
                "bucketNames": "alpha-bucket,beta-bucket",
            },
        }
    )
    doc, sidecar = _run_cpgNG(
        cpgNG,
        tmp_path,
        ["s3-lifecycle-policy-check"],
        ddb_table,
        extra=["--group", GROUP],
    )
    params = doc["Resources"]["S3LifecyclePolicyCheckRule"]["Properties"]["InputParameters"]
    assert params["targetTransitionDays"] == "30"
    assert params["targetTransitionStorageClass"] == "STANDARD_IA"
    assert params["bucketNames"] == "alpha-bucket,beta-bucket"
    assert isinstance(params["bucketNames"], str)
    with sidecar.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    by_name = {row["parameter_name"]: row for row in rows}
    assert by_name["bucketNames"]["required"] == "false"
    assert by_name["targetTransitionDays"]["catalog_default"] == "30"


def test_cpgNG_placeholder_omitted_and_required_without_default(cpgNG, ddb_table, tmp_path):
    put_profile(ddb_table, "desired-instance-type")
    put_paramdef(
        ddb_table,
        "desired-instance-type",
        "instanceType",
        required=True,
        default_value="99999",
    )
    put_profile(ddb_table, "api-gw-endpoint-type-check")
    put_paramdef(
        ddb_table,
        "api-gw-endpoint-type-check",
        "endpointConfigurationTypes",
        required=True,
        default_value="",
    )
    doc, _ = _run_cpgNG(
        cpgNG,
        tmp_path,
        ["desired-instance-type", "api-gw-endpoint-type-check"],
        ddb_table,
    )
    assert (
        doc["Resources"]["DesiredInstanceTypeRule"]["Properties"]["InputParameters"]
        == {}
    )
    assert (
        doc["Resources"]["ApiGwEndpointTypeCheckRule"]["Properties"]["InputParameters"]
        == {}
    )


def test_upackNG_maps_unique_parameter_key(pack_yaml):
    text = _mini_pack(
        ["api-gw-endpoint-type-check", "s3-bucket-public-read-prohibited"],
        {"api-gw-endpoint-type-check": {"endpointConfigurationTypes": "PRIVATE"}},
    )
    rules = pack_yaml.index_rules(text)
    mapping = pack_yaml.map_error_to_rule(
        "InvalidParameterValueException: endpointConfigurationTypes is invalid",
        rules,
    )
    assert mapping.rule.config_rule_name == "api-gw-endpoint-type-check"
    assert mapping.matched_on == "parameter_key"


def test_upackNG_shared_oldest_version_fails_closed(pack_yaml):
    text = _mini_pack(
        [
            "eks-cluster-oldest-supported-version",
            "eks-cluster-supported-version",
        ],
        {
            "eks-cluster-oldest-supported-version": {"oldestVersionSupported": "1.28"},
            "eks-cluster-supported-version": {"oldestVersionSupported": "1.28"},
        },
    )
    rules = pack_yaml.index_rules(text)
    with pytest.raises(pack_yaml.RuleMappingError, match="Ambiguous"):
        pack_yaml.map_error_to_rule("oldestVersionSupported is required", rules)


def test_upackNG_shared_application_names_fails_closed(pack_yaml):
    text = _mini_pack(
        [
            "ec2-managedinstance-applications-required",
            "ec2-managedinstance-applications-blacklisted",
        ],
        {
            "ec2-managedinstance-applications-required": {"applicationNames": "ssm"},
            "ec2-managedinstance-applications-blacklisted": {"applicationNames": "ssm"},
        },
    )
    rules = pack_yaml.index_rules(text)
    with pytest.raises(pack_yaml.RuleMappingError, match="Ambiguous"):
        pack_yaml.map_error_to_rule("applicationNames is required", rules)


def test_upackNG_suggested_cli_not_executed(upackNG, pack_yaml, tmp_path, ddb_table):
    src = tmp_path / "expiry.yml"
    src.write_text(
        _mini_pack(
            ["bedrock-agentcore-memory-event-expiry-duration"],
            {"bedrock-agentcore-memory-event-expiry-duration": {"minEventExpiryDuration": "7"}},
        ),
        encoding="utf-8",
    )
    scan_before = len(ddb_table.scan().get("Items") or [])

    def fake_deploy(pack_name, template_path):
        text = Path(template_path).read_text(encoding="utf-8")
        if "BedrockAgentcoreMemoryEventExpiryDurationRule" in text:
            return (
                False,
                "InvalidParameterValueException: Invalid parameter values for rule "
                "bedrock-agentcore-memory-event-expiry-duration",
            )
        return True, "CREATE_COMPLETE"

    result = upackNG.run_loop(
        "param-smoke",
        src,
        artifacts_dir=tmp_path / "artifacts",
        deploy_fn=fake_deploy,
    )
    errors = result.errors_path.read_text(encoding="utf-8")
    assert "suggested catalog repair (not executed)" in errors
    assert "aws dynamodb put-item" in errors
    assert "GROUP#26y#BINDING#default" in errors
    assert group_items(ddb_table) == []
    assert len(ddb_table.scan().get("Items") or []) == scan_before
    name, value, dtype = upackNG.infer_repair_parameter(
        "Invalid parameter minEventExpiryDuration",
        pack_yaml.index_rules(src.read_text(encoding="utf-8"))[0],
    )
    assert name == "minEventExpiryDuration"
    assert value in {"7", "30"}
    assert dtype in {"S", "N"}
