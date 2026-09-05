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
