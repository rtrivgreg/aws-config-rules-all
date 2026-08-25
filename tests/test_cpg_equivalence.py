#!/usr/bin/env python3
"""
Equivalence test: cpg.py (YAML SOT) vs cpgNG.py (DynamoDB catalog).

Runs both generators against a single managed rule ("access-keys-rotated")
and asserts semantic equality of the produced conformance-pack YAML.

cpgNG.py is exercised offline by mocking boto3 DynamoDB so no live AWS
credentials or table are required.

Layout (all under tests/):
  fixtures/rules_single.json   - JSON array with one rule name
  fixtures/truth_single.yml    - minimal YAML SOT for cpg.py
  test_cpg_equivalence.py      - this file

Run from the repository root:
  pytest tests/test_cpg_equivalence.py -v
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest
import yaml

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[1]
PYTHON_DIR = REPO_ROOT / "python"
FIXTURES = Path(__file__).resolve().parent / "fixtures"

RULES_JSON = FIXTURES / "rules_single.json"
TRUTH_YAML = FIXTURES / "truth_single.yml"

RULE_ID = "access-keys-rotated"
DESCRIPTION = (
    "Checks if active IAM access keys are rotated (changed) within the number "
    "of days specified in maxAccessKeyAge. The rule is NON_COMPLIANT if access "
    "keys are not rotated within the specified time period. The default value "
    "is 90 days."
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_module(name: str, path: Path):
    """Load a single-file script as a module without requiring package layout."""
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _normalize_pack(doc: Dict[str, Any]) -> Dict[str, Any]:
    """
    Reduce a conformance-pack document to the fields we care about for
    semantic comparison.  Ignores pure formatting / key-order differences.
    """
    resources = doc.get("Resources") or {}
    normalized: Dict[str, Any] = {}

    for logical_id, res in sorted(resources.items()):
        props = res.get("Properties") or {}
        entry: Dict[str, Any] = {
            "Type": res.get("Type"),
            "ConfigRuleName": props.get("ConfigRuleName"),
            "Source": props.get("Source"),
            "InputParameters": props.get("InputParameters") or {},
        }
        if "Description" in props and props["Description"] is not None:
            # Match the whitespace normalization both tools apply
            entry["Description"] = " ".join(str(props["Description"]).split())
        if "Scope" in props and props["Scope"] is not None:
            scope = props["Scope"]
            crt = scope.get("ComplianceResourceTypes") or []
            entry["Scope"] = {"ComplianceResourceTypes": sorted(crt)}
        normalized[logical_id] = entry

    return {
        "AWSTemplateFormatVersion": doc.get("AWSTemplateFormatVersion"),
        "Description": " ".join(str(doc.get("Description") or "").split()),
        "Resources": normalized,
    }


def _run_cpg(tmp_path: Path) -> Dict[str, Any]:
    """Invoke cpg.main() with fixture inputs; return parsed pack YAML."""
    cpg = _load_module("cpg_under_test", PYTHON_DIR / "cpg.py")

    out_base = tmp_path / "cpg_out.yml"
    # cpg always writes <stem>-part01.yml
    expected = tmp_path / "cpg_out-part01.yml"

    argv = [
        "cpg.py",
        "-r", str(RULES_JSON),
        "-t", str(TRUTH_YAML),
        "-o", str(out_base),
    ]
    with patch.object(sys, "argv", argv):
        cpg.main()

    assert expected.is_file(), f"cpg.py did not write {expected}"
    with expected.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def _make_mock_table() -> MagicMock:
    """
    Build a MagicMock that behaves like the subset of a boto3 DynamoDB Table
    that cpgNG.fetch_rule_from_dynamodb uses for a single rule.
    """
    table = MagicMock()

    # get_item for RULE_PROFILE
    def get_item(Key):
        pk, sk = Key["pk"], Key["sk"]
        if pk == f"RULE#{RULE_ID}" and sk == f"PROFILE#{RULE_ID}":
            return {
                "Item": {
                    "pk": pk,
                    "sk": sk,
                    "entity_type": "RULE_PROFILE",
                    "rule_id": RULE_ID,
                    "source_identifier": "ACCESS_KEYS_ROTATED",
                    "description": DESCRIPTION,
                    "severity": "Medium",
                    "scopes": ["AWS::IAM::User"],
                    "managed_rule": True,
                }
            }
        # No binding requested in the default test path
        return {}

    # query for PARAMETER_DEF items
    def query(KeyConditionExpression=None, ExpressionAttributeValues=None, **_):
        return {
            "Items": [
                {
                    "pk": f"RULE#{RULE_ID}",
                    "sk": "PARAMDEF#maxAccessKeyAge",
                    "entity_type": "PARAMETER_DEF",
                    "rule_id": RULE_ID,
                    "parameter_name": "maxAccessKeyAge",
                    "data_type": "string",
                    "required": True,
                    "default_value": "90",
                }
            ]
        }

    table.get_item.side_effect = get_item
    table.query.side_effect = query
    return table


def _run_cpgNG(tmp_path: Path) -> Dict[str, Any]:
    """Invoke cpgNG.main() with DynamoDB mocked; return parsed pack YAML."""
    cpgNG = _load_module("cpgNG_under_test", PYTHON_DIR / "cpgNG.py")

    out_base = tmp_path / "cpgNG_out.yml"
    expected = tmp_path / "cpgNG_out-part01.yml"
    mock_table = _make_mock_table()

    argv = [
        "cpgNG.py",
        "-r", str(RULES_JSON),
        "-o", str(out_base),
        "--table", "y62db-config-rule-catalog-test",
    ]

    with patch.object(sys, "argv", argv), \
         patch.object(cpgNG, "_get_dynamodb_table", return_value=mock_table):
        cpgNG.main()

    assert expected.is_file(), f"cpgNG.py did not write {expected}"
    with expected.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_fixtures_exist():
    assert RULES_JSON.is_file(), f"Missing fixture: {RULES_JSON}"
    assert TRUTH_YAML.is_file(), f"Missing fixture: {TRUTH_YAML}"
    assert (PYTHON_DIR / "cpg.py").is_file()
    assert (PYTHON_DIR / "cpgNG.py").is_file()


def test_single_rule_semantic_equivalence(tmp_path):
    """
    Both generators, given equivalent source data for one rule, must produce
    semantically identical conformance-pack documents.
    """
    cpg_doc = _run_cpg(tmp_path)
    cpgNG_doc = _run_cpgNG(tmp_path)

    left = _normalize_pack(cpg_doc)
    right = _normalize_pack(cpgNG_doc)

    # Same top-level shape
    assert left["AWSTemplateFormatVersion"] == right["AWSTemplateFormatVersion"]
    assert left["Description"] == right["Description"]

    # Exactly one resource, same logical ID
    assert set(left["Resources"]) == set(right["Resources"])
    assert "AccessKeysRotatedRule" in left["Resources"]

    # Deep compare the single resource
    assert left["Resources"]["AccessKeysRotatedRule"] == right["Resources"]["AccessKeysRotatedRule"]


def test_resource_fields_match_expected(tmp_path):
    """Sanity-check that the shared output contains the expected rule fields."""
    doc = _normalize_pack(_run_cpg(tmp_path))
    res = doc["Resources"]["AccessKeysRotatedRule"]

    assert res["Type"] == "AWS::Config::ConfigRule"
    assert res["ConfigRuleName"] == "access-keys-rotated"
    assert res["Source"] == {
        "Owner": "AWS",
        "SourceIdentifier": "ACCESS_KEYS_ROTATED",
    }
    assert res["InputParameters"] == {"maxAccessKeyAge": "90"}
    assert res["Scope"]["ComplianceResourceTypes"] == ["AWS::IAM::User"]
    assert "maxAccessKeyAge" in res["Description"]
