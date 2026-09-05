#!/usr/bin/env python3
"""Fixtures, catalog helpers, and bindingsNG checks for the param smoketest."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import boto3
import pytest
from moto import mock_aws

from test_param_smoketest import (
    BINDING,
    CFN_INPUTS,
    FIXTURE,
    GROUP,
    NIAID_SAMPLE_DEFAULTS,
    PYTHON_DIR,
    REGION,
    REQUIRED_NO_DEFAULT,
    SOURCE_IDENTIFIERS,
    TABLE_NAME,
    _load_module,
)


@pytest.fixture(scope="module")
def bindingsNG():
    return _load_module("bindingsNG_smoke", PYTHON_DIR / "bindingsNG.py")


@pytest.fixture(scope="module")
def cpgNG():
    return _load_module("cpgNG_smoke", PYTHON_DIR / "cpgNG.py")


@pytest.fixture(scope="module")
def pack_yaml():
    return _load_module("pack_yaml_smoke", PYTHON_DIR / "pack_yaml.py")


@pytest.fixture(scope="module")
def upackNG(pack_yaml):
    sys.modules["pack_yaml"] = pack_yaml
    return _load_module("upackNG_smoke", PYTHON_DIR / "upackNG.py")


@pytest.fixture(scope="module")
def fixture_rules() -> List[str]:
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert isinstance(data, list)
    return [str(item) for item in data]


def source_identifier(rule_id: str) -> str:
    return SOURCE_IDENTIFIERS[rule_id]


def build_cfn_body(rule_id: str) -> bytes:
    sid = source_identifier(rule_id)
    parameters: Dict[str, Any] = {
        "ConfigRuleName": {"Type": "String", "Default": rule_id},
    }
    input_parameters: Dict[str, Any] = {}
    for name, spec in CFN_INPUTS[rule_id].items():
        entry: Dict[str, Any] = {"Type": "String"}
        if not spec["required"]:
            entry["Default"] = spec["default"] if spec["default"] is not None else ""
        parameters[name] = entry
        input_parameters[name] = {"Ref": name}
    doc = {
        "AWSTemplateFormatVersion": "2010-09-09",
        "Parameters": parameters,
        "Resources": {
            "Rule": {
                "Type": "AWS::Config::ConfigRule",
                "Properties": {
                    "ConfigRuleName": {"Ref": "ConfigRuleName"},
                    "Description": f"Official description for {rule_id}.",
                    "Source": {"Owner": "AWS", "SourceIdentifier": sid},
                    "InputParameters": input_parameters,
                },
            }
        },
    }
    return json.dumps(doc).encode("utf-8")


def http_get_factory():
    def _http_get(url: str) -> bytes:
        for rule_id, sid in SOURCE_IDENTIFIERS.items():
            if sid in url:
                return build_cfn_body(rule_id)
        raise FileNotFoundError(url)

    return _http_get


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
        yield boto3.resource("dynamodb", region_name=REGION).Table(TABLE_NAME)


def put_profile(table, rule_id: str) -> None:
    table.put_item(
        Item={
            "pk": f"RULE#{rule_id}",
            "sk": f"PROFILE#{rule_id}",
            "entity_type": "RULE_PROFILE",
            "rule_id": rule_id,
            "source_identifier": source_identifier(rule_id),
            "description": f"Official description for {rule_id}.",
            "managed_rule": True,
        }
    )


def put_paramdef(table, rule_id: str, name: str, *, required: bool, default_value: str = "") -> None:
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


def seed_cfn_catalog(table, rule_ids: List[str], *, niaid_samples: bool = True) -> None:
    for rule_id in rule_ids:
        put_profile(table, rule_id)
        samples = NIAID_SAMPLE_DEFAULTS.get(rule_id, {}) if niaid_samples else {}
        for name, spec in CFN_INPUTS[rule_id].items():
            default = samples.get(name)
            if default is None:
                default = spec["default"] if spec["default"] is not None else ""
            put_paramdef(
                table, rule_id, name, required=bool(spec["required"]), default_value=default
            )


def group_items(table) -> List[Dict[str, Any]]:
    return [
        item
        for item in (table.scan().get("Items") or [])
        if str(item.get("sk") or "").startswith("GROUP#")
    ]
