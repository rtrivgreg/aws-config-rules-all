#!/usr/bin/env python3
"""
Agentic deploy-and-strip loop around python/upack.py.

Deploys a conformance pack, and on each boto3/Config failure identifies the
offending rule, removes that rule's YAML block from a working copy, and
redeploys until success, exhaustion, or an unmappable error.
"""

from __future__ import annotations

import json
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, List, Optional, Tuple

PYTHON_DIR = Path(__file__).resolve().parent
if str(PYTHON_DIR) not in sys.path:
    sys.path.insert(0, str(PYTHON_DIR))

import pack_yaml  # noqa: E402


def _load_upack():
    import upack as upack_mod

    return upack_mod


def _client_error_type():
    try:
        from botocore.exceptions import ClientError
    except ImportError:  # pragma: no cover - unit tests without AWS SDK
        return Exception
    return ClientError


REPO_ROOT = PYTHON_DIR.parent
DEFAULT_ARTIFACTS_DIR = REPO_ROOT / "tests" / "artifacts"
DEFAULT_TABLE = "y62db-config-rule-catalog"
DEFAULT_REGION = "us-east-1"
DEFAULT_GROUP = "26y"
DEFAULT_BINDING = "default"

DeployFn = Callable[[str, Path], Tuple[bool, str]]


class UnmappableError(RuntimeError):
    """Deploy failed and the error could not be mapped to one rule."""


@dataclass
class StripRecord:
    iteration: int
    logical_id: str
    config_rule_name: str
    matched_on: str
    error: str


@dataclass
class LoopResult:
    success: bool
    reason: str
    stripped: List[StripRecord] = field(default_factory=list)
    working_path: Optional[Path] = None
    errors_path: Optional[Path] = None
    stripped_path: Optional[Path] = None


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _format_client_error(exc) -> str:
    err = (exc.response or {}).get("Error") or {}
    code = err.get("Code") or "ClientError"
    message = err.get("Message") or str(exc)
    payload = {
        "Error": err,
        "ResponseMetadata": (exc.response or {}).get("ResponseMetadata"),
    }
    return f"{code}: {message}\n{json.dumps(payload, default=str, indent=2)}"


def _append(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(text)
        if not text.endswith("\n"):
            handle.write("\n")


def wait_for_pack_settled(client, name: str) -> Tuple[str, str]:
    """Poll until a terminal COMPLETE or FAILED state (create or update)."""
    upack = _load_upack()
    ClientError = _client_error_type()
    while True:
        try:
            resp = client.describe_conformance_pack_status(ConformancePackNames=[name])
        except ClientError as exc:
            code = (getattr(exc, "response", {}) or {}).get("Error", {}).get("Code")
            if code == "NoSuchConformancePackException":
                print("Conformance pack status not yet available, waiting...")
                time.sleep(upack.POLL_INTERVAL_SECONDS)
                continue
            raise

        details = resp.get("ConformancePackStatusDetails") or []
        if not details:
            print("Conformance pack status empty, waiting...")
            time.sleep(upack.POLL_INTERVAL_SECONDS)
            continue

        status = details[0]
        state = status.get("ConformancePackState") or ""
        reason = status.get("ConformancePackStatusReason") or ""
        print(f"Current state: {state} {('- ' + reason) if reason else ''}")

        if state.endswith("_IN_PROGRESS"):
            time.sleep(upack.POLL_INTERVAL_SECONDS)
            continue
        return state, reason


def deploy_with_upack(pack_name: str, template_path: Path) -> Tuple[bool, str]:
    """Reuse upack.py load + PutConformancePack; accept create or update."""
    import boto3
    from botocore.exceptions import ClientError

    upack = _load_upack()
    template_body = upack.load_template(str(template_path))
    client = boto3.client("config")
    print(f"Deploying conformance pack '{pack_name}' from '{template_path}'")
    try:
        resp = client.put_conformance_pack(
            ConformancePackName=pack_name,
            TemplateBody=template_body,
        )
        print(f"PutConformancePack initiated, ARN: {resp.get('ConformancePackArn')}")
    except ClientError as exc:
        return False, _format_client_error(exc)

    try:
        state, reason = wait_for_pack_settled(client, pack_name)
    except ClientError as exc:
        return False, _format_client_error(exc)

    if state.endswith("_COMPLETE"):
        return True, f"{state}"
    if state.endswith("_FAILED"):
        return False, f"{state}: {reason}".strip()
    return False, f"Unexpected conformance pack state: {state} {reason}".strip()


def _is_numeric(value: str) -> bool:
    try:
        float(value)
        return True
    except (TypeError, ValueError):
        return False


def _duration_like(name: str) -> bool:
    lowered = (name or "").lower()
    return any(token in lowered for token in ("duration", "expiry", "expire", "days", "age"))


def infer_repair_parameter(error_text: str, rule: pack_yaml.RuleRef) -> Tuple[str, str, str]:
    """Return (parameter_name, create_value, dynamodb_type)."""
    values = dict(rule.parameter_values)
    tokens = list(pack_yaml.extract_error_tokens(error_text))
    name = None
    for token in tokens:
        for key in rule.parameter_keys:
            if token.lower() == key.lower():
                name = key
                break
        if name:
            break
    if name is None and len(rule.parameter_keys) == 1:
        name = rule.parameter_keys[0]
    if name is None:
        return "TODO_PARAM", "TODO_VALUE", "S"

    raw = values.get(name, "")
    if raw == "" and _duration_like(name):
        raw = "30"
    if raw == "":
        raw = "TODO_VALUE"
    dtype = "N" if _is_numeric(raw) or _duration_like(name) else "S"
    if raw == "TODO_VALUE":
        dtype = "S"
    return name, raw, dtype


def update_sample_value(param_name: str, create_value: str, dtype: str) -> str:
    if dtype == "N" and _duration_like(param_name):
        return "90"
    return create_value


def render_catalog_cli(
    config_rule_name: str,
    param_name: str,
    create_value: str,
    dtype: str,
    *,
    table: str = DEFAULT_TABLE,
    region: str = DEFAULT_REGION,
    group: str = DEFAULT_GROUP,
    binding: str = DEFAULT_BINDING,
) -> str:
    rule_id = config_rule_name or "TODO_RULE"
    pk = f"RULE#{rule_id}"
    sk = f"GROUP#{group}#BINDING#{binding}"
    gsi1sk = f"RULE#{rule_id}#BINDING#{binding}"
    update_value = update_sample_value(param_name, create_value, dtype)
    placeholder_note = ""
    if param_name == "TODO_PARAM":
        placeholder_note = (
            "# parameter could not be inferred from the error or YAML; edit TODO_PARAM\n"
        )
    create = f'''# CREATE
NOW=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
aws dynamodb put-item \\
  --table-name {table} \\
  --region {region} \\
  --condition-expression "attribute_not_exists(pk) AND attribute_not_exists(sk)" \\
  --item "{{\n    \"pk\": {{\"S\": \"{pk}\"}},\n    \"sk\": {{\"S\": \"{sk}\"}},\n    \"gsi1pk\": {{\"S\": \"GROUP#{group}\"}},\n    \"gsi1sk\": {{\"S\": \"{gsi1sk}\"}},\n    \"payload\": {{\"M\": {{\n      \"version\": {{\"N\": \"1\"}},\n      \"status\": {{\"S\": \"ACTIVE\"}},\n      \"{param_name}\": {{\"{dtype}\": \"{create_value}\"}}\n    }}}},\n    \"created_at\": {{\"S\": \"$NOW\"}},\n    \"updated_at\": {{\"S\": \"$NOW\"}}\n  }}"'''
    update = f'''# UPDATE
NOW=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
aws dynamodb update-item \\
  --table-name {table} \\
  --region {region} \\
  --key '{{\n    "pk": {{"S": "{pk}"}},\n    "sk": {{"S": "{sk}"}}\n  }}' \\
  --update-expression "SET payload.{param_name} = :d, payload.version = :ver, updated_at = :now" \\
  --condition-expression "attribute_exists(pk) AND attribute_exists(sk)" \\
  --expression-attribute-values '{{\n    ":d": {{"{dtype}": "{update_value}"}},\n    ":ver": {{"N": "2"}},\n    ":now": {{"S": "'"$NOW"'"}}\n  }}' \\
  --return-values ALL_NEW'''
    return placeholder_note + create + "\n\n" + update


def artifact_paths(template_path: Path, artifacts_dir: Path) -> Tuple[Path, Path, Path]:
    stem = template_path.stem
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    return (
        artifacts_dir / f"{stem}.working.yml",
        artifacts_dir / f"{stem}.errors.txt",
        artifacts_dir / f"{stem}.stripped-rules.txt",
    )


def run_loop(
    pack_name: str,
    template_path: Path,
    artifacts_dir: Optional[Path] = None,
    deploy_fn: Optional[DeployFn] = None,
) -> LoopResult:
    template_path = template_path.resolve()
    if not template_path.is_file():
        raise FileNotFoundError(f"Template file not found: {template_path}")

    artifacts_dir = (artifacts_dir or DEFAULT_ARTIFACTS_DIR).resolve()
    working_path, errors_path, stripped_path = artifact_paths(template_path, artifacts_dir)
    deploy = deploy_fn or deploy_with_upack

    original = pack_yaml.load_yaml_text(template_path)
    pack_yaml.save_yaml_text(working_path, original)
    errors_path.write_text("", encoding="utf-8")
    stripped_path.write_text("", encoding="utf-8")

    stripped: List[StripRecord] = []
    seen = set()
    iteration = 0

    while True:
        iteration += 1
        working_text = pack_yaml.load_yaml_text(working_path)
        rules = pack_yaml.index_rules(working_text)
        if not rules:
            reason = "no rules remain in the working template"
            print(reason)
            return LoopResult(
                False, reason, stripped, working_path, errors_path, stripped_path
            )

        print(
            f"\n=== iteration {iteration}: {len(rules)} rule(s) in {working_path.name} ==="
        )
        ok, error_text = deploy(pack_name, working_path)
        if ok:
            reason = "deploy succeeded"
            print(reason)
            return LoopResult(
                True, reason, stripped, working_path, errors_path, stripped_path
            )

        _append(
            errors_path,
            f"--- iteration {iteration} @ {_now()} ---\n{error_text.rstrip()}\n",
        )
        print(f"Deploy failed:\n{error_text}")

        try:
            mapping = pack_yaml.map_error_to_rule(error_text, rules)
        except pack_yaml.RuleMappingError as exc:
            _append(errors_path, f"UNMAPPABLE: {exc}\n")
            raise UnmappableError(str(exc)) from exc

        rule = mapping.rule
        assert rule is not None
        param_name, create_value, dtype = infer_repair_parameter(error_text, rule)
        cli = render_catalog_cli(rule.config_rule_name, param_name, create_value, dtype)
        _append(
            errors_path,
            (
                f"\n# mapped: {rule.logical_id}  {rule.config_rule_name}  "
                f"matched_on={mapping.matched_on}\n"
                "# suggested catalog repair (not executed)\n"
                f"{cli}\n"
            ),
        )
        if rule.logical_id in seen:
            raise UnmappableError(
                f"Mapped rule '{rule.logical_id}' was already stripped; refusing to retry"
            )
        seen.add(rule.logical_id)

        working_text = pack_yaml.remove_rule_block(working_text, rule.logical_id)
        pack_yaml.save_yaml_text(working_path, working_text)

        record = StripRecord(
            iteration=iteration,
            logical_id=rule.logical_id,
            config_rule_name=rule.config_rule_name,
            matched_on=mapping.matched_on,
            error=error_text,
        )
        stripped.append(record)
        _append(
            stripped_path,
            (
                f"{iteration}\t{rule.logical_id}\t{rule.config_rule_name}\t"
                f"{mapping.matched_on}\t{param_name}\t{error_text.splitlines()[0]}\n"
            ),
        )
        print(
            f"Stripped {rule.logical_id} ({rule.config_rule_name}) "
            f"matched on {mapping.matched_on}"
        )


def main(argv: Optional[List[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) != 2:
        print(f"Usage: {Path(sys.argv[0]).name} <conformance-pack-name> <template-file-path>")
        return 1

    pack_name, template = argv
    try:
        result = run_loop(pack_name, Path(template))
    except UnmappableError as exc:
        print(f"Stopping: {exc}")
        return 2
    except FileNotFoundError as exc:
        print(exc)
        return 1

    print(f"Working copy: {result.working_path}")
    print(f"Errors:       {result.errors_path}")
    print(f"Stripped:     {result.stripped_path}")
    print(f"Rules removed: {len(result.stripped)}")
    for rec in result.stripped:
        print(f"  - {rec.logical_id} ({rec.config_rule_name})")
    return 0 if result.success else 3


if __name__ == "__main__":
    sys.exit(main())
