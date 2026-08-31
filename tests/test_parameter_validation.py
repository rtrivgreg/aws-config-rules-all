#!/usr/bin/env python3
"""
Parameter and input-validation tests for cpg.py and cpgNG.py.
"""

from __future__ import annotations

import csv
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
PYTHON_DIR = REPO_ROOT / "python"

RULE_ID = "access-keys-rotated"
DESCRIPTION = (
    "Checks if active IAM access keys are rotated (changed) within the number "
    "of days specified in maxAccessKeyAge. The rule is NON_COMPLIANT if access "
    "keys are not rotated within the specified time period. The default value "
    "is 90 days."
)


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def cpg():
    return _load_module("cpg_param_val", PYTHON_DIR / "cpg.py")


@pytest.fixture(scope="module")
def cpgNG():
    return _load_module("cpgNG_param_val", PYTHON_DIR / "cpgNG.py")


@pytest.mark.parametrize("mod_name", ["cpg", "cpgNG"])
def test_load_rules_json_rejects_non_list(mod_name, cpg, cpgNG, tmp_path):
    mod = cpg if mod_name == "cpg" else cpgNG
    bad = tmp_path / "not_a_list.json"
    bad.write_text(json.dumps({"rule": "access-keys-rotated"}), encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        mod.load_rules_json(bad)
    assert exc.value.code == 1


@pytest.mark.parametrize("mod_name", ["cpg", "cpgNG"])
def test_load_rules_json_rejects_non_string_items(mod_name, cpg, cpgNG, tmp_path):
    mod = cpg if mod_name == "cpg" else cpgNG
    bad = tmp_path / "bad_items.json"
    bad.write_text(json.dumps(["access-keys-rotated", 42, None]), encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        mod.load_rules_json(bad)
    assert exc.value.code == 1


@pytest.mark.parametrize("mod_name", ["cpg", "cpgNG"])
def test_load_rules_json_rejects_empty_after_strip(mod_name, cpg, cpgNG, tmp_path):
    mod = cpg if mod_name == "cpg" else cpgNG
    bad = tmp_path / "empty.json"
    bad.write_text(json.dumps(["", "   ", "\t"]), encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        mod.load_rules_json(bad)
    assert exc.value.code == 1


@pytest.mark.parametrize("mod_name", ["cpg", "cpgNG"])
def test_load_rules_json_rejects_empty_array(mod_name, cpg, cpgNG, tmp_path):
    mod = cpg if mod_name == "cpg" else cpgNG
    bad = tmp_path / "empty_arr.json"
    bad.write_text("[]", encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        mod.load_rules_json(bad)
    assert exc.value.code == 1


@pytest.mark.parametrize("mod_name", ["cpg", "cpgNG"])
def test_load_rules_json_accepts_and_strips(mod_name, cpg, cpgNG, tmp_path):
    mod = cpg if mod_name == "cpg" else cpgNG
    good = tmp_path / "good.json"
    good.write_text(
        json.dumps(["  access-keys-rotated  ", "s3-bucket-public-read-prohibited"]),
        encoding="utf-8",
    )
    rules = mod.load_rules_json(good)
    assert rules == ["access-keys-rotated", "s3-bucket-public-read-prohibited"]


@pytest.mark.parametrize("mod_name", ["cpg", "cpgNG"])
def test_load_rules_json_rejects_invalid_json(mod_name, cpg, cpgNG, tmp_path):
    mod = cpg if mod_name == "cpg" else cpgNG
    bad = tmp_path / "invalid.json"
    bad.write_text("{not valid json", encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        mod.load_rules_json(bad)
    assert exc.value.code == 1


def _run_cpg_with_truth(cpg, tmp_path: Path, truth: Dict[str, Any], rules: List[str]) -> Dict[str, Any]:
    rules_path = tmp_path / "rules.json"
    truth_path = tmp_path / "truth.yml"
    out_base = tmp_path / "out.yml"
    expected = tmp_path / "out-part01.yml"
    rules_path.write_text(json.dumps(rules), encoding="utf-8")
    truth_path.write_text(yaml.safe_dump(truth), encoding="utf-8")
    argv = ["cpg.py", "-r", str(rules_path), "-t", str(truth_path), "-o", str(out_base)]
    with patch.object(sys, "argv", argv):
        cpg.main()
    with expected.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def test_cpg_input_parameters_null_becomes_empty_map(cpg, tmp_path):
    truth = {
        "AWSTemplateFormatVersion": "2010-09-09",
        "Resources": {
            "AccessKeysRotatedRule": {
                "Type": "AWS::Config::ConfigRule",
                "Properties": {
                    "ConfigRuleName": RULE_ID,
                    "Source": {"Owner": "AWS", "SourceIdentifier": "ACCESS_KEYS_ROTATED"},
                    "InputParameters": None,
                },
            }
        },
    }
    doc = _run_cpg_with_truth(cpg, tmp_path, truth, [RULE_ID])
    assert doc["Resources"]["AccessKeysRotatedRule"]["Properties"]["InputParameters"] == {}


def test_cpg_input_parameters_missing_becomes_empty_map(cpg, tmp_path):
    truth = {
        "AWSTemplateFormatVersion": "2010-09-09",
        "Resources": {
            "AccessKeysRotatedRule": {
                "Type": "AWS::Config::ConfigRule",
                "Properties": {
                    "ConfigRuleName": RULE_ID,
                    "Source": {"Owner": "AWS", "SourceIdentifier": "ACCESS_KEYS_ROTATED"},
                },
            }
        },
    }
    doc = _run_cpg_with_truth(cpg, tmp_path, truth, [RULE_ID])
    assert doc["Resources"]["AccessKeysRotatedRule"]["Properties"]["InputParameters"] == {}


def test_cpg_input_parameters_non_dict_becomes_empty_map(cpg, tmp_path):
    truth = {
        "AWSTemplateFormatVersion": "2010-09-09",
        "Resources": {
            "AccessKeysRotatedRule": {
                "Type": "AWS::Config::ConfigRule",
                "Properties": {
                    "ConfigRuleName": RULE_ID,
                    "Source": {"Owner": "AWS", "SourceIdentifier": "ACCESS_KEYS_ROTATED"},
                    "InputParameters": "not-a-map",
                },
            }
        },
    }
    doc = _run_cpg_with_truth(cpg, tmp_path, truth, [RULE_ID])
    assert doc["Resources"]["AccessKeysRotatedRule"]["Properties"]["InputParameters"] == {}


def test_cpg_input_parameters_preserved_when_valid_map(cpg, tmp_path):
    truth = {
        "AWSTemplateFormatVersion": "2010-09-09",
        "Resources": {
            "AccessKeysRotatedRule": {
                "Type": "AWS::Config::ConfigRule",
                "Properties": {
                    "ConfigRuleName": RULE_ID,
                    "Source": {"Owner": "AWS", "SourceIdentifier": "ACCESS_KEYS_ROTATED"},
                    "InputParameters": {"maxAccessKeyAge": "90"},
                },
            }
        },
    }
    doc = _run_cpg_with_truth(cpg, tmp_path, truth, [RULE_ID])
    assert doc["Resources"]["AccessKeysRotatedRule"]["Properties"]["InputParameters"] == {"maxAccessKeyAge": "90"}


def _mock_table(* , profile=None, param_defs=None, binding_item=None):
    table = MagicMock()

    def get_item(Key):
        pk, sk = Key["pk"], Key["sk"]
        if profile and pk == f"RULE#{RULE_ID}" and sk == f"PROFILE#{RULE_ID}":
            return {"Item": profile}
        if binding_item and sk.startswith("GROUP#"):
            return {"Item": binding_item}
        return {}

    def query(KeyConditionExpression=None, ExpressionAttributeValues=None, **_):
        return {"Items": list(param_defs or [])}

    table.get_item.side_effect = get_item
    table.query.side_effect = query
    return table


def _run_cpgNG(cpgNG, tmp_path: Path, rules: List[str], table: MagicMock, extra_argv: Optional[List[str]] = None):
    rules_path = tmp_path / "rules.json"
    out_base = tmp_path / "ng_out.yml"
    expected = tmp_path / "ng_out-part01.yml"
    rules_path.write_text(json.dumps(rules), encoding="utf-8")
    argv = ["cpgNG.py", "-r", str(rules_path), "-o", str(out_base), "--table", "test-catalog"]
    if extra_argv:
        argv.extend(extra_argv)
    with patch.object(sys, "argv", argv), patch.object(cpgNG, "_get_dynamodb_table", return_value=table):
        cpgNG.main()
    with expected.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def _default_profile():
    return {
        "pk": f"RULE#{RULE_ID}",
        "sk": f"PROFILE#{RULE_ID}",
        "entity_type": "RULE_PROFILE",
        "rule_id": RULE_ID,
        "source_identifier": "ACCESS_KEYS_ROTATED",
        "description": DESCRIPTION,
        "scopes": ["AWS::IAM::User"],
        "managed_rule": True,
    }


def test_cpgNG_parameter_def_defaults_appear_in_input_parameters(cpgNG, tmp_path):
    table = _mock_table(
        profile=_default_profile(),
        param_defs=[
            {"pk": f"RULE#{RULE_ID}", "sk": "PARAMDEF#maxAccessKeyAge", "parameter_name": "maxAccessKeyAge", "data_type": "string", "required": True, "default_value": "90"},
            {"pk": f"RULE#{RULE_ID}", "sk": "PARAMDEF#emptyDefault", "parameter_name": "emptyDefault", "data_type": "string", "required": False, "default_value": ""},
            {"pk": f"RULE#{RULE_ID}", "sk": "PARAMDEF#optionalWithDefault", "parameter_name": "optionalWithDefault", "data_type": "string", "required": False, "default_value": "catalog-only"},
        ],
    )
    doc = _run_cpgNG(cpgNG, tmp_path, [RULE_ID], table)
    props = doc["Resources"]["AccessKeysRotatedRule"]["Properties"]
    assert props["InputParameters"] == {"maxAccessKeyAge": "90"}
    assert "optionalWithDefault" not in props["InputParameters"]


def test_cpgNG_binding_overrides_parameter_defaults(cpgNG, tmp_path):
    table = _mock_table(
        profile=_default_profile(),
        param_defs=[{"pk": f"RULE#{RULE_ID}", "sk": "PARAMDEF#maxAccessKeyAge", "parameter_name": "maxAccessKeyAge", "data_type": "string", "required": True, "default_value": "90"}],
        binding_item={"pk": f"RULE#{RULE_ID}", "sk": "GROUP#niaid#BINDING#default", "payload": {"parameter_values": {"maxAccessKeyAge": "30"}, "status": "ACTIVE", "version": 1}},
    )
    doc = _run_cpgNG(cpgNG, tmp_path, [RULE_ID], table, extra_argv=["--group", "niaid", "--binding", "default"])
    assert doc["Resources"]["AccessKeysRotatedRule"]["Properties"]["InputParameters"] == {"maxAccessKeyAge": "30"}


def test_cpgNG_binding_payload_without_parameter_values_key(cpgNG, tmp_path):
    table = _mock_table(
        profile=_default_profile(),
        param_defs=[{"pk": f"RULE#{RULE_ID}", "sk": "PARAMDEF#maxAccessKeyAge", "parameter_name": "maxAccessKeyAge", "data_type": "string", "required": True, "default_value": "90"}],
        binding_item={"pk": f"RULE#{RULE_ID}", "sk": "GROUP#niaid#BINDING#default", "payload": {"maxAccessKeyAge": "45", "status": "ACTIVE", "version": 2}},
    )
    doc = _run_cpgNG(cpgNG, tmp_path, [RULE_ID], table, extra_argv=["--group", "niaid"])
    assert doc["Resources"]["AccessKeysRotatedRule"]["Properties"]["InputParameters"] == {"maxAccessKeyAge": "45"}


def test_cpgNG_missing_profile_yields_minimal_rule_with_empty_params(cpgNG, tmp_path):
    table = _mock_table(profile=None, param_defs=[])
    doc = _run_cpgNG(cpgNG, tmp_path, [RULE_ID], table)
    props = doc["Resources"]["AccessKeysRotatedRule"]["Properties"]
    assert props["InputParameters"] == {}
    assert "Description" not in props


def test_cpgNG_input_parameters_always_a_dict(cpgNG, tmp_path):
    table = _mock_table(profile=_default_profile(), param_defs=[])
    doc = _run_cpgNG(cpgNG, tmp_path, [RULE_ID], table)
    assert isinstance(doc["Resources"]["AccessKeysRotatedRule"]["Properties"]["InputParameters"], dict)


def test_cpgNG_optional_catalog_default_omitted_unless_bound(cpgNG, tmp_path):
    table = _mock_table(
        profile=_default_profile(),
        param_defs=[{"pk": f"RULE#{RULE_ID}", "sk": "PARAMDEF#optionalWithDefault", "parameter_name": "optionalWithDefault", "data_type": "string", "required": False, "default_value": "catalog-only"}],
        binding_item={"pk": f"RULE#{RULE_ID}", "sk": "GROUP#niaid#BINDING#default", "payload": {"parameter_values": {"optionalWithDefault": "pinned"}}},
    )
    unbound = _run_cpgNG(cpgNG, tmp_path, [RULE_ID], table)
    assert unbound["Resources"]["AccessKeysRotatedRule"]["Properties"]["InputParameters"] == {}
    bound_dir = tmp_path / "bound"
    bound_dir.mkdir()
    bound = _run_cpgNG(cpgNG, bound_dir, [RULE_ID], table, extra_argv=["--group", "niaid", "--binding", "default"])
    assert bound["Resources"]["AccessKeysRotatedRule"]["Properties"]["InputParameters"] == {"optionalWithDefault": "pinned"}


def test_cpgNG_placeholder_default_is_omitted(cpgNG, tmp_path):
    table = _mock_table(
        profile=_default_profile(),
        param_defs=[{"pk": f"RULE#{RULE_ID}", "sk": "PARAMDEF#targetExpirationDays", "parameter_name": "targetExpirationDays", "data_type": "string", "required": True, "default_value": "99999"}],
    )
    doc = _run_cpgNG(cpgNG, tmp_path, [RULE_ID], table)
    assert doc["Resources"]["AccessKeysRotatedRule"]["Properties"]["InputParameters"] == {}


def test_cpgNG_writes_parameter_sidecar(cpgNG, tmp_path):
    table = _mock_table(
        profile=_default_profile(),
        param_defs=[
            {"pk": f"RULE#{RULE_ID}", "sk": "PARAMDEF#maxAccessKeyAge", "parameter_name": "maxAccessKeyAge", "data_type": "string", "required": True, "default_value": "90"},
            {"pk": f"RULE#{RULE_ID}", "sk": "PARAMDEF#optionalWithDefault", "parameter_name": "optionalWithDefault", "data_type": "number", "required": False, "default_value": "7"},
        ],
    )
    _run_cpgNG(cpgNG, tmp_path, [RULE_ID], table)
    assert not (tmp_path / "ng_out-part01.json").exists()
    sidecar = tmp_path / "ng_out-part01.csv"
    assert sidecar.is_file()
    assert sidecar.read_bytes().startswith(b"\xef\xbb\xbf")
    with sidecar.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert list(rows[0].keys()) == [
        "name", "description", "scope", "parameter_name", "data_type",
        "required", "catalog_default", "binding_value", "emitted",
    ]
    assert all(row["name"] == RULE_ID for row in rows)
    assert all(row["description"].startswith("OPTIONAL FIELDS EXIST ") for row in rows)
    assert DESCRIPTION in rows[0]["description"]
    assert rows[0]["scope"] == "AWS::IAM::User"
    by_name = {row["parameter_name"]: row for row in rows}
    assert by_name["maxAccessKeyAge"]["required"] == "true"
    assert by_name["maxAccessKeyAge"]["emitted"] == "90"
    assert by_name["optionalWithDefault"]["required"] == "false"
    assert by_name["optionalWithDefault"]["emitted"] == "omitted"
