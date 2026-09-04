#!/usr/bin/env python3
"""Unit tests for upackNG error mapping, YAML strip, and the deploy loop."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
PYTHON_DIR = REPO_ROOT / "python"
AIML = REPO_ROOT / "tests" / "aiml-part01.yml"


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def pack_yaml():
    return _load_module("pack_yaml_ut", PYTHON_DIR / "pack_yaml.py")


@pytest.fixture(scope="module")
def upackNG(pack_yaml):
    sys.modules["pack_yaml"] = pack_yaml
    return _load_module("upackNG_ut", PYTHON_DIR / "upackNG.py")


MINI_PACK = """\
AWSTemplateFormatVersion: '2010-09-09'
Description: fixture
Resources:
  AlbWafEnabledRule:
    Type: AWS::Config::ConfigRule
    Properties:
      ConfigRuleName: alb-waf-enabled
      Source:
        Owner: AWS
        SourceIdentifier: ALB_WAF_ENABLED
      InputParameters: {}
  BedrockDataSourceEncryptionEnabledRule:
    Type: AWS::Config::ConfigRule
    Properties:
      ConfigRuleName: bedrock-data-source-encryption-enabled
      Source:
        Owner: AWS
        SourceIdentifier: BEDROCK_DATA_SOURCE_ENCRYPTION_ENABLED
      InputParameters: {}
  ApiGwEndpointTypeCheckRule:
    Type: AWS::Config::ConfigRule
    Properties:
      ConfigRuleName: api-gw-endpoint-type-check
      Source:
        Owner: AWS
        SourceIdentifier: API_GW_ENDPOINT_TYPE_CHECK
      InputParameters:
        endpointConfigurationTypes: PRIVATE
"""


def test_index_rules_from_aiml(pack_yaml):
    text = AIML.read_text(encoding="utf-8")
    rules = pack_yaml.index_rules(text)
    ids = {r.logical_id for r in rules}
    assert "BedrockDataSourceEncryptionEnabledRule" in ids
    assert "AlbWafEnabledRule" in ids
    assert len(rules) >= 20


def test_remove_rule_block_preserves_neighbors(pack_yaml):
    new_text = pack_yaml.remove_rule_block(MINI_PACK, "BedrockDataSourceEncryptionEnabledRule")
    left = pack_yaml.remaining_logical_ids(new_text)
    assert left == ["AlbWafEnabledRule", "ApiGwEndpointTypeCheckRule"]
    assert "BedrockDataSourceEncryptionEnabledRule" not in new_text
    assert "alb-waf-enabled" in new_text
    assert "api-gw-endpoint-type-check" in new_text


def test_remove_missing_block_raises(pack_yaml):
    with pytest.raises(pack_yaml.RuleMappingError):
        pack_yaml.remove_rule_block(MINI_PACK, "DoesNotExistRule")


def test_map_by_logical_id(pack_yaml):
    rules = pack_yaml.index_rules(MINI_PACK)
    mapping = pack_yaml.map_error_to_rule(
        "Template error in resource BedrockDataSourceEncryptionEnabledRule",
        rules,
    )
    assert mapping.rule.logical_id == "BedrockDataSourceEncryptionEnabledRule"
    assert mapping.matched_on == "logical_id"


def test_map_by_config_rule_name(pack_yaml):
    rules = pack_yaml.index_rules(MINI_PACK)
    mapping = pack_yaml.map_error_to_rule(
        "InvalidParameterValueException: Invalid parameter values for rule "
        "bedrock-data-source-encryption-enabled: kmsKeyId is required",
        rules,
    )
    assert mapping.rule.logical_id == "BedrockDataSourceEncryptionEnabledRule"
    assert mapping.matched_on == "config_rule_name"


def test_map_by_source_identifier(pack_yaml):
    rules = pack_yaml.index_rules(MINI_PACK)
    mapping = pack_yaml.map_error_to_rule(
        "CREATE_FAILED: Parameter missing for BEDROCK_DATA_SOURCE_ENCRYPTION_ENABLED",
        rules,
    )
    assert mapping.rule.logical_id == "BedrockDataSourceEncryptionEnabledRule"
    assert mapping.matched_on == "source_identifier"


def test_map_by_unique_parameter_key(pack_yaml):
    rules = pack_yaml.index_rules(MINI_PACK)
    mapping = pack_yaml.map_error_to_rule(
        "InvalidParameterValueException: endpointConfigurationTypes is invalid",
        rules,
    )
    assert mapping.rule.logical_id == "ApiGwEndpointTypeCheckRule"
    assert mapping.matched_on == "parameter_key"


def test_map_ambiguous_fails_closed(pack_yaml):
    text = MINI_PACK.replace(
        "InputParameters: {}",
        "InputParameters:\n        sharedKey: x",
        1,
    )
    text = text.replace(
        "endpointConfigurationTypes: PRIVATE",
        "sharedKey: y",
    )
    rules = pack_yaml.index_rules(text)
    with pytest.raises(pack_yaml.RuleMappingError, match="Ambiguous"):
        pack_yaml.map_error_to_rule("Invalid parameter sharedKey", rules)


def test_map_no_match_fails_closed(pack_yaml):
    rules = pack_yaml.index_rules(MINI_PACK)
    with pytest.raises(pack_yaml.RuleMappingError, match="Could not map"):
        pack_yaml.map_error_to_rule("Something exploded in an unrelated service", rules)


def test_loop_strips_two_aiml_errors_and_preserves_original(upackNG, tmp_path):
    src = tmp_path / "aiml-part01.yml"
    src.write_text(AIML.read_text(encoding="utf-8"), encoding="utf-8")
    original = src.read_text(encoding="utf-8")
    artifacts = tmp_path / "artifacts"

    planned_errors = [
        "InvalidParameterValueException: Invalid parameter values for rule "
        "bedrock-data-source-encryption-enabled",
        "CREATE_FAILED: Resource BedrockAgentcoreMemoryEventExpiryDurationRule "
        "failed template validation",
    ]
    calls = {"n": 0}

    def fake_deploy(pack_name, template_path):
        calls["n"] += 1
        text = Path(template_path).read_text(encoding="utf-8")
        if "BedrockDataSourceEncryptionEnabledRule" in text:
            return False, planned_errors[0]
        if "BedrockAgentcoreMemoryEventExpiryDurationRule" in text:
            return False, planned_errors[1]
        return True, "CREATE_COMPLETE"

    result = upackNG.run_loop(
        "aiml-ng-test",
        src,
        artifacts_dir=artifacts,
        deploy_fn=fake_deploy,
    )

    assert result.success is True
    assert [rec.logical_id for rec in result.stripped] == [
        "BedrockDataSourceEncryptionEnabledRule",
        "BedrockAgentcoreMemoryEventExpiryDurationRule",
    ]
    assert src.read_text(encoding="utf-8") == original
    working = yaml.safe_load(result.working_path.read_text(encoding="utf-8"))
    resources = working["Resources"]
    assert "BedrockDataSourceEncryptionEnabledRule" not in resources
    assert "BedrockAgentcoreMemoryEventExpiryDurationRule" not in resources
    assert "AlbWafEnabledRule" in resources
    errors = result.errors_path.read_text(encoding="utf-8")
    assert "bedrock-data-source-encryption-enabled" in errors
    assert "BedrockAgentcoreMemoryEventExpiryDurationRule" in errors
    stripped_log = result.stripped_path.read_text(encoding="utf-8")
    assert stripped_log.count("\n") >= 2
    assert calls["n"] == 3


def test_loop_does_not_retry_same_rule(upackNG, tmp_path):
    src = tmp_path / "pack.yml"
    src.write_text(MINI_PACK, encoding="utf-8")

    def always_same_error(pack_name, template_path):
        return False, "Invalid parameter values for rule bedrock-data-source-encryption-enabled"

    with pytest.raises(upackNG.UnmappableError, match="Could not map|already stripped"):
        upackNG.run_loop(
            "x",
            src,
            artifacts_dir=tmp_path / "artifacts",
            deploy_fn=always_same_error,
        )

    working = (tmp_path / "artifacts" / "pack.working.yml").read_text(encoding="utf-8")
    assert "BedrockDataSourceEncryptionEnabledRule" not in working
    stripped = (tmp_path / "artifacts" / "pack.stripped-rules.txt").read_text(encoding="utf-8")
    assert stripped.count("BedrockDataSourceEncryptionEnabledRule") == 1


def test_cli_usage(upackNG, capsys):
    rc = upackNG.main([])
    assert rc == 1
    assert "Usage:" in capsys.readouterr().out
