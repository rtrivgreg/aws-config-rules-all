#!/usr/bin/env python3
"""Parameter-shape smoketest for bindingsNG, cpgNG, and upackNG.

Uses tests/fixtures/param-smoketest.json. Catalog and CFN are mocked.
No live DynamoDB writes. No PutConformancePack.
"""

from __future__ import annotations

import csv
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import boto3
import pytest
import yaml
from moto import mock_aws

REPO_ROOT = Path(__file__).resolve().parents[1]
PYTHON_DIR = REPO_ROOT / "python"
FIXTURE = REPO_ROOT / "tests" / "fixtures" / "param-smoketest.json"

TABLE_NAME = "y62db-config-rule-catalog"
REGION = "us-east-1"
GROUP = "26y"
BINDING = "default"

# CFN InputParameters only (ConfigRuleName / MaximumExecutionFrequency omitted).
# required=True iff the CFN Parameters entry has no Default key.
# default is the CFN Default string, or None when the key is absent.
CFN_INPUTS: Dict[str, Dict[str, Dict[str, Any]]] = {
    "s3-bucket-public-read-prohibited": {},
    "alb-waf-enabled": {
        "wafWebAclIds": {"required": False, "default": ""},
    },
    "access-keys-rotated": {
        "maxAccessKeyAge": {"required": False, "default": "90"},
    },
    "encrypted-volumes": {
        "kmsId": {"required": False, "default": ""},
    },
    "api-gw-endpoint-type-check": {
        "endpointConfigurationTypes": {"required": True, "default": None},
    },
    "desired-instance-type": {
        "instanceType": {"required": True, "default": None},
    },
    "vpc-endpoint-enabled": {
        "serviceNames": {"required": True, "default": None},
        "vpcIds": {"required": False, "default": ""},
        "scopeConfigResourceTypes": {"required": False, "default": ""},
    },
    "s3-lifecycle-policy-check": {
        "targetTransitionDays": {"required": False, "default": ""},
        "targetExpirationDays": {"required": False, "default": ""},
        "targetTransitionStorageClass": {"required": False, "default": ""},
        "targetPrefix": {"required": False, "default": ""},
        "bucketNames": {"required": False, "default": ""},
    },
    "restricted-common-ports": {
        "blockedPort1": {"required": False, "default": "20"},
        "blockedPort2": {"required": False, "default": "21"},
        "blockedPort3": {"required": False, "default": "3389"},
        "blockedPort4": {"required": False, "default": "3306"},
        "blockedPort5": {"required": False, "default": "4333"},
        "blockedPorts": {"required": False, "default": ""},
    },
    "iam-password-policy": {
        "RequireUppercaseCharacters": {"required": False, "default": "true"},
        "RequireLowercaseCharacters": {"required": False, "default": "true"},
        "RequireSymbols": {"required": False, "default": "true"},
        "RequireNumbers": {"required": False, "default": "true"},
        "MinimumPasswordLength": {"required": False, "default": "14"},
        "PasswordReusePrevention": {"required": False, "default": "24"},
        "MaxPasswordAge": {"required": False, "default": "90"},
    },
    "eks-cluster-oldest-supported-version": {
        "oldestVersionSupported": {"required": True, "default": None},
    },
    "eks-cluster-supported-version": {
        "oldestVersionSupported": {"required": True, "default": None},
    },
    "ec2-managedinstance-applications-required": {
        "applicationNames": {"required": True, "default": None},
        "platformType": {"required": False, "default": ""},
    },
    "ec2-managedinstance-applications-blacklisted": {
        "applicationNames": {"required": True, "default": None},
        "platformType": {"required": False, "default": ""},
    },
    "bedrock-agentcore-memory-event-expiry-duration": {
        "minEventExpiryDuration": {"required": False, "default": "7"},
    },
    "cloudwatch-alarm-resource-check": {
        "resourceType": {"required": True, "default": None},
        "metricName": {"required": True, "default": None},
    },
}

SOURCE_IDENTIFIERS = {
    "s3-bucket-public-read-prohibited": "S3_BUCKET_PUBLIC_READ_PROHIBITED",
    "alb-waf-enabled": "ALB_WAF_ENABLED",
    "access-keys-rotated": "ACCESS_KEYS_ROTATED",
    "encrypted-volumes": "ENCRYPTED_VOLUMES",
    "api-gw-endpoint-type-check": "API_GW_ENDPOINT_TYPE_CHECK",
    "desired-instance-type": "DESIRED_INSTANCE_TYPE",
    "vpc-endpoint-enabled": "VPC_ENDPOINT_ENABLED",
    "s3-lifecycle-policy-check": "S3_LIFECYCLE_POLICY_CHECK",
    "restricted-common-ports": "RESTRICTED_INCOMING_TRAFFIC",
    "iam-password-policy": "IAM_PASSWORD_POLICY",
    "eks-cluster-oldest-supported-version": "EKS_CLUSTER_OLDEST_SUPPORTED_VERSION",
    "eks-cluster-supported-version": "EKS_CLUSTER_SUPPORTED_VERSION",
    "ec2-managedinstance-applications-required": "EC2_MANAGEDINSTANCE_APPLICATIONS_REQUIRED",
    "ec2-managedinstance-applications-blacklisted": "EC2_MANAGEDINSTANCE_APPLICATIONS_BLACKLISTED",
    "bedrock-agentcore-memory-event-expiry-duration": "BEDROCK_AGENTCORE_MEMORY_EVENT_EXPIRY_DURATION",
    "cloudwatch-alarm-resource-check": "CLOUDWATCH_ALARM_RESOURCE_CHECK",
}

# Catalog-only NIAID sample defaults (not CFN Defaults).
NIAID_SAMPLE_DEFAULTS = {
    "s3-lifecycle-policy-check": {
        "targetTransitionDays": "30",
        "targetExpirationDays": "90",
        "targetTransitionStorageClass": "STANDARD_IA",
    }
}

REQUIRED_NO_DEFAULT = (
    "api-gw-endpoint-type-check",
    "desired-instance-type",
    "vpc-endpoint-enabled",
    "eks-cluster-oldest-supported-version",
    "eks-cluster-supported-version",
    "ec2-managedinstance-applications-required",
    "ec2-managedinstance-applications-blacklisted",
    "cloudwatch-alarm-resource-check",
)


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod
