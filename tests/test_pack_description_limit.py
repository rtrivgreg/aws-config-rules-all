#!/usr/bin/env python3
"""Pack Description stays official and <=256; CSV keeps optional-parameter prefix."""

from __future__ import annotations

import csv
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
PYTHON_DIR = REPO_ROOT / "python"

RDS_RULE = "rds-meets-restore-time-target"
RDS_DESCRIPTION = (
    "Checks if the restore time of Amazon Relational Database Service (Amazon RDS) "
    "instances meets specified duration. The rule is NON_COMPLIANT if "
    "LatestRestoreExecutionTimeMinutes of an Amazon RDS instance is greater than "
    "maxRestoreTime minutes."
)


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _mock_table(profile: Dict[str, Any], param_defs: List[Dict[str, Any]]) -> MagicMock:
    table = MagicMock()

    def get_item(Key):
        if Key["sk"].startswith("PROFILE#"):
            return {"Item": profile}
        return {}

    def query(KeyConditionExpression=None, ExpressionAttributeValues=None, **_):
        return {"Items": list(param_defs)}

    table.get_item.side_effect = get_item
    table.query.side_effect = query
    return table


def _run_cpgNG(cpgNG, tmp_path: Path, rules: List[str], table: MagicMock):
    rules_path = tmp_path / "rules.json"
    out_base = tmp_path / "ng_out.yml"
    pack_path = tmp_path / "ng_out-part01.yml"
    sidecar_path = tmp_path / "ng_out-part01.csv"
    rules_path.write_text(json.dumps(rules), encoding="utf-8")
    argv = ["cpgNG.py", "-r", str(rules_path), "-o", str(out_base), "--table", "test-catalog"]
    with patch.object(sys, "argv", argv), patch.object(cpgNG, "_get_dynamodb_table", return_value=table):
        cpgNG.main()
    with pack_path.open(encoding="utf-8") as handle:
        pack = yaml.safe_load(handle)
    with sidecar_path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    return pack, rows


def test_pack_description_excludes_prefix_and_stays_within_256(tmp_path):
    cpgNG = _load_module("cpgNG_desc_limit", PYTHON_DIR / "cpgNG.py")
    assert len(RDS_DESCRIPTION) < cpgNG.CONFIG_RULE_DESCRIPTION_MAX
    assert len(cpgNG.OPTIONAL_FIELDS_PREFIX + RDS_DESCRIPTION) > cpgNG.CONFIG_RULE_DESCRIPTION_MAX

    profile = {
        "pk": f"RULE#{RDS_RULE}",
        "sk": f"PROFILE#{RDS_RULE}",
        "rule_id": RDS_RULE,
        "source_identifier": "RDS_MEETS_RESTORE_TIME_TARGET",
        "description": RDS_DESCRIPTION,
        "scopes": ["AWS::RDS::DBInstance"],
    }
    param_defs = [
        {
            "parameter_name": "maxRestoreTime",
            "data_type": "int",
            "required": True,
            "default_value": "60",
        },
        {
            "parameter_name": "resourceTags",
            "data_type": "string",
            "required": False,
            "default_value": "",
        },
    ]
    pack, rows = _run_cpgNG(cpgNG, tmp_path, [RDS_RULE], _mock_table(profile, param_defs))
    props = pack["Resources"]["RdsMeetsRestoreTimeTargetRule"]["Properties"]

    assert props["Description"] == RDS_DESCRIPTION
    assert len(props["Description"]) <= cpgNG.CONFIG_RULE_DESCRIPTION_MAX
    assert not props["Description"].startswith(cpgNG.OPTIONAL_FIELDS_PREFIX)
    assert props["InputParameters"] == {"maxRestoreTime": "60"}
    assert props["Source"]["SourceIdentifier"] == "RDS_MEETS_RESTORE_TIME_TARGET"

    csv_desc = rows[0]["description"]
    assert csv_desc.startswith(cpgNG.OPTIONAL_FIELDS_PREFIX)
    assert RDS_DESCRIPTION in csv_desc
    assert len(csv_desc) > cpgNG.CONFIG_RULE_DESCRIPTION_MAX


def test_clamp_does_not_touch_sidecar_helper():
    cpgNG = _load_module("cpgNG_desc_clamp", PYTHON_DIR / "cpgNG.py")
    long_official = "x" * 300
    assert len(cpgNG.pack_description(long_official)) == cpgNG.CONFIG_RULE_DESCRIPTION_MAX
    csv_text = cpgNG.sidecar_description(
        long_official,
        [{"name": "resourceTags", "required": False}],
    )
    assert csv_text.startswith(cpgNG.OPTIONAL_FIELDS_PREFIX)
    assert csv_text.endswith(long_official)
    assert len(csv_text) == len(cpgNG.OPTIONAL_FIELDS_PREFIX) + 300
