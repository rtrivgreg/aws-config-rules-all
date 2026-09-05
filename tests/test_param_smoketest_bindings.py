#!/usr/bin/env python3
"""bindingsNG assertions for the parameter-shape smoketest."""

from __future__ import annotations

from typing import Dict, List, Optional

from test_param_smoketest import CFN_INPUTS, FIXTURE, GROUP, REGION, REQUIRED_NO_DEFAULT, TABLE_NAME
from test_param_smoketest_harness import (
    BINDING,
    bindingsNG,
    ddb_table,
    fixture_rules,
    group_items,
    http_get_factory,
    put_paramdef,
    put_profile,
    seed_cfn_catalog,
    source_identifier,
)


def _mini_pack(rules: List[str], bound: Optional[Dict[str, Dict[str, str]]] = None) -> str:
    bound = bound or {}
    resources = []
    for rule_id in rules:
        logical = "".join(part.capitalize() for part in rule_id.split("-") if part) + "Rule"
        params = bound.get(rule_id, {})
        if params:
            body = "\n".join(f"        {k}: {v}" for k, v in params.items())
            ip = f"      InputParameters:\n{body}\n"
        else:
            ip = "      InputParameters: {}\n"
        resources.append(
            f"  {logical}:\n"
            f"    Type: AWS::Config::ConfigRule\n"
            f"    Properties:\n"
            f"      ConfigRuleName: {rule_id}\n"
            f"      Source:\n"
            f"        Owner: AWS\n"
            f"        SourceIdentifier: {source_identifier(rule_id)}\n"
            f"{ip}"
        )
    return (
        "AWSTemplateFormatVersion: '2010-09-09'\n"
        "Description: param-smoketest fixture\n"
        "Resources:\n" + "".join(resources)
    )


def test_fixture_covers_matrix_cells(fixture_rules):
    assert fixture_rules == list(CFN_INPUTS.keys())
    assert len(fixture_rules) == 16
    assert CFN_INPUTS["s3-bucket-public-read-prohibited"] == {}
    assert CFN_INPUTS["vpc-endpoint-enabled"]["serviceNames"]["required"] is True


def test_bindings_update_dry_run_writes_nothing(bindingsNG, ddb_table, fixture_rules):
    seed_cfn_catalog(ddb_table, fixture_rules)
    before = ddb_table.scan().get("Items") or []
    rc = bindingsNG.run(
        bindingsNG.parse_args(
            [
                "--update",
                "--dry-run",
                "--rules-json",
                str(FIXTURE),
                "--group",
                GROUP,
                "--table",
                TABLE_NAME,
                "--region",
                REGION,
            ]
        ),
        table=ddb_table,
        http_get=http_get_factory(),
    )
    assert rc == 0
    assert len(ddb_table.scan().get("Items") or []) == len(before)
    assert group_items(ddb_table) == []


def test_bindings_update_required_flags_match_cfn(bindingsNG, ddb_table, fixture_rules):
    seed_cfn_catalog(ddb_table, fixture_rules, niaid_samples=False)
    rc = bindingsNG.run(
        bindingsNG.parse_args(
            [
                "--update",
                "--rules-json",
                str(FIXTURE),
                "--group",
                GROUP,
                "--table",
                TABLE_NAME,
                "--region",
                REGION,
            ]
        ),
        table=ddb_table,
        http_get=http_get_factory(),
    )
    assert rc == 0
    assert group_items(ddb_table) == []
    for rule_id, params in CFN_INPUTS.items():
        for name, spec in params.items():
            item = ddb_table.get_item(
                Key={"pk": f"RULE#{rule_id}", "sk": f"PARAMDEF#{name}"}
            )["Item"]
            assert bool(item["required"]) is bool(spec["required"]), (rule_id, name)


def test_bindings_update_keeps_niaid_sample_when_cfn_default_empty(bindingsNG, ddb_table):
    rule = "s3-lifecycle-policy-check"
    seed_cfn_catalog(ddb_table, [rule], niaid_samples=True)
    rc = bindingsNG.run(
        bindingsNG.parse_args(
            ["--update", "--rule", rule, "--group", GROUP, "--table", TABLE_NAME, "--region", REGION]
        ),
        table=ddb_table,
        http_get=http_get_factory(),
    )
    assert rc == 0
    days = ddb_table.get_item(Key={"pk": f"RULE#{rule}", "sk": "PARAMDEF#targetTransitionDays"})["Item"]
    assert days["required"] is False
    assert days["default_value"] == "30"
    assert group_items(ddb_table) == []


def test_bindings_default_blocks_required_without_value(bindingsNG, ddb_table):
    seed_cfn_catalog(ddb_table, list(REQUIRED_NO_DEFAULT), niaid_samples=False)
    rc = bindingsNG.run(
        bindingsNG.parse_args(
            ["--rules-json", str(FIXTURE), "--group", GROUP, "--table", TABLE_NAME, "--region", REGION]
        ),
        table=ddb_table,
        http_get=http_get_factory(),
    )
    assert rc == 0
    for rule_id in REQUIRED_NO_DEFAULT:
        got = ddb_table.get_item(
            Key={"pk": f"RULE#{rule_id}", "sk": f"GROUP#{GROUP}#BINDING#{BINDING}"}
        )
        assert "Item" not in got, rule_id


def test_bindings_placeholder_does_not_satisfy_required(bindingsNG, ddb_table):
    rule = "desired-instance-type"
    put_profile(ddb_table, rule)
    put_paramdef(ddb_table, rule, "instanceType", required=True, default_value="99999")
    rc = bindingsNG.run(
        bindingsNG.parse_args(
            ["--rule", rule, "--group", GROUP, "--table", TABLE_NAME, "--region", REGION]
        ),
        table=ddb_table,
        http_get=http_get_factory(),
    )
    assert rc == 0
    got = ddb_table.get_item(
        Key={"pk": f"RULE#{rule}", "sk": f"GROUP#{GROUP}#BINDING#{BINDING}"}
    )
    assert "Item" not in got
