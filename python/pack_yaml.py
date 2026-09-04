#!/usr/bin/env python3
"""YAML surgery helpers for conformance-pack templates."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, List, Optional, Sequence, Tuple

import yaml


COMMON_ERROR_TOKENS = frozenset(
    {
        "an",
        "and",
        "aws",
        "awstemplateformatversion",
        "client",
        "clienterror",
        "config",
        "configrule",
        "conformance",
        "conformancepack",
        "create_failed",
        "createfailed",
        "description",
        "error",
        "exception",
        "failed",
        "failure",
        "for",
        "from",
        "input",
        "inputparameters",
        "invalid",
        "invalidparametervalueexception",
        "missing",
        "not",
        "of",
        "pack",
        "parameter",
        "parameters",
        "properties",
        "putconformancepack",
        "required",
        "resource",
        "resources",
        "rule",
        "rules",
        "source",
        "sourceidentifier",
        "template",
        "the",
        "this",
        "type",
        "update_failed",
        "updatefailed",
        "validation",
        "value",
        "values",
        "with",
    }
)

TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_-]{2,}")
REQUIRED_PARAM_RE = re.compile(
    r"required parameter\s*\[(?P<bracket>[^\]]+)\]"
    r"|required parameter\s+(?P<bare>[A-Za-z][A-Za-z0-9_-]*)",
    re.IGNORECASE,
)

# One AWS error can apply to several remaining rules that share a required
# parameter. Map to every known owner and strip one remaining rule per loop.
WELL_KNOWN_REQUIRED_PARAMS = {
    "secretkeys": ("ecs-no-environment-secrets",),
    "oldestversionsupported": (
        "eks-cluster-supported-version",
        "eks-cluster-oldest-supported-version",
        "eks-nodegroup-supported-version-check",
    ),
    "metricname,resourcetype": ("cloudwatch-alarm-resource-check",),
    "applicationnames": (
        "ec2-managedinstance-applications-blacklisted",
        "ec2-managedinstance-applications-required",
    ),
}


@dataclass(frozen=True)
class RuleRef:
    logical_id: str
    config_rule_name: str = ""
    source_identifier: str = ""
    parameter_keys: Tuple[str, ...] = ()
    parameter_values: Tuple[Tuple[str, str], ...] = ()
    description: str = ""

    def search_fields(self) -> Sequence[str]:
        fields = [self.logical_id, self.config_rule_name, self.source_identifier]
        fields.extend(self.parameter_keys)
        return [f for f in fields if f]


@dataclass
class MappingResult:
    rule: Optional[RuleRef] = None
    matched_on: str = ""
    candidates: List[str] = field(default_factory=list)
    tokens: List[str] = field(default_factory=list)


class RuleMappingError(ValueError):
    """Raised when an error cannot be mapped to exactly one rule."""


def load_yaml_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def save_yaml_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if text and not text.endswith("\n"):
        text += "\n"
    path.write_text(text, encoding="utf-8")


def parse_pack(text: str) -> dict:
    doc = yaml.safe_load(text) or {}
    if not isinstance(doc, dict):
        raise ValueError("Conformance pack YAML must be a mapping")
    return doc


def index_rules(text: str) -> List[RuleRef]:
    doc = parse_pack(text)
    resources = doc.get("Resources") or {}
    if not isinstance(resources, dict):
        return []
    rules: List[RuleRef] = []
    for logical_id, body in resources.items():
        if not isinstance(body, dict):
            continue
        if body.get("Type") != "AWS::Config::ConfigRule":
            continue
        props = body.get("Properties") or {}
        source = props.get("Source") or {}
        params = props.get("InputParameters") or {}
        if isinstance(params, dict):
            param_keys = tuple(str(k) for k in params.keys())
            param_values = tuple(
                (str(k), "" if v is None else str(v)) for k, v in params.items()
            )
        else:
            param_keys = ()
            param_values = ()
        rules.append(
            RuleRef(
                logical_id=str(logical_id),
                config_rule_name=str(props.get("ConfigRuleName") or ""),
                source_identifier=str(source.get("SourceIdentifier") or ""),
                parameter_keys=param_keys,
                parameter_values=param_values,
                description=str(props.get("Description") or ""),
            )
        )
    return rules


def remaining_logical_ids(text: str) -> List[str]:
    return [rule.logical_id for rule in index_rules(text)]


def _resource_block_span(text: str, logical_id: str) -> Optional[Tuple[int, int]]:
    """Return [start, end) character offsets of a top-level Resources entry."""
    lines = text.splitlines(keepends=True)
    header = re.compile(rf"^  {re.escape(logical_id)}:\s*(#.*)?$")
    next_peer = re.compile(r"^  \S")
    section_end = re.compile(r"^\S")

    start = None
    for i, line in enumerate(lines):
        if header.match(line.rstrip("\n")):
            start = i
            break
    if start is None:
        return None

    end = len(lines)
    for j in range(start + 1, len(lines)):
        raw = lines[j].rstrip("\n")
        if raw == "":
            continue
        if next_peer.match(raw) or section_end.match(raw):
            end = j
            break

    start_off = sum(len(line) for line in lines[:start])
    end_off = sum(len(line) for line in lines[:end])
    return start_off, end_off


def remove_rule_block(text: str, logical_id: str) -> str:
    span = _resource_block_span(text, logical_id)
    if span is None:
        raise RuleMappingError(f"No YAML block found for rule '{logical_id}'")
    start, end = span
    new_text = text[:start] + text[end:]
    new_text = re.sub(r"\n{3,}", "\n\n", new_text)
    return new_text


def extract_required_parameters(error_text: str) -> List[str]:
    match = REQUIRED_PARAM_RE.search(error_text or "")
    if not match:
        return []
    raw = (match.group("bracket") or match.group("bare") or "").strip()
    return [part.strip() for part in raw.split(",") if part.strip()]


def extract_required_parameter(error_text: str) -> Optional[str]:
    parts = extract_required_parameters(error_text)
    return parts[0] if parts else None


def _map_missing_required_parameter(
    param: str, rules: Sequence[RuleRef]
) -> Optional[RuleRef]:
    param_l = param.lower()
    known = WELL_KNOWN_REQUIRED_PARAMS.get(param_l) or ()
    if not known:
        combo = ",".join(sorted(p.strip().lower() for p in param.split(",") if p.strip()))
        known = WELL_KNOWN_REQUIRED_PARAMS.get(combo) or ()
    if isinstance(known, str):
        known = (known,)
    if known:
        remaining = []
        for name in known:
            remaining.extend(
                r
                for r in rules
                if r.config_rule_name.lower() == name
                or name.replace("-", "") in r.logical_id.lower()
            )
        seen_ids = set()
        ordered = []
        for rule in rules:
            if rule in remaining and rule.logical_id not in seen_ids:
                seen_ids.add(rule.logical_id)
                ordered.append(rule)
        if ordered:
            return ordered[0]

    hits = []
    for rule in rules:
        blob = " ".join(
            [
                rule.logical_id,
                rule.config_rule_name,
                rule.source_identifier,
                rule.description,
                " ".join(rule.parameter_keys),
            ]
        ).lower()
        if param_l in blob.replace("-", "").replace("_", "") or param_l in blob:
            hits.append(rule)
            continue
        compact_name = rule.config_rule_name.replace("-", "").replace("_", "").lower()
        compact_param = param_l.replace("_", "")
        if compact_param and compact_param in compact_name:
            hits.append(rule)
    if len(hits) == 1:
        return hits[0]
    return None


def extract_error_tokens(error_text: str) -> List[str]:
    tokens: List[str] = []
    seen = set()
    for match in TOKEN_RE.finditer(error_text or ""):
        raw = match.group(0)
        key = raw.lower()
        if key in COMMON_ERROR_TOKENS or key in seen:
            continue
        seen.add(key)
        tokens.append(raw)
    return tokens


def _exact_field_matches(rules: Iterable[RuleRef], token: str) -> List[Tuple[RuleRef, str]]:
    hits: List[Tuple[RuleRef, str]] = []
    token_l = token.lower()
    for rule in rules:
        if rule.logical_id.lower() == token_l:
            hits.append((rule, "logical_id"))
        elif rule.config_rule_name.lower() == token_l:
            hits.append((rule, "config_rule_name"))
        elif rule.source_identifier.lower() == token_l:
            hits.append((rule, "source_identifier"))
        elif any(key.lower() == token_l for key in rule.parameter_keys):
            hits.append((rule, "parameter_key"))
    return hits


def map_error_to_rule(error_text: str, rules: Sequence[RuleRef]) -> MappingResult:
    if not rules:
        raise RuleMappingError("No rules remain in the working template")

    tokens = extract_error_tokens(error_text)
    result = MappingResult(tokens=list(tokens))

    exact: List[Tuple[RuleRef, str]] = []
    for token in tokens:
        exact.extend(_exact_field_matches(rules, token))

    for field_name in ("logical_id", "config_rule_name", "source_identifier"):
        field_hits = [(rule, field) for rule, field in exact if field == field_name]
        unique_ids = {rule.logical_id for rule, _ in field_hits}
        if len(unique_ids) == 1:
            rule = field_hits[0][0]
            result.rule = rule
            result.matched_on = field_name
            result.candidates = [rule.logical_id]
            return result
        if len(unique_ids) > 1:
            result.candidates = sorted(unique_ids)
            raise RuleMappingError(
                f"Ambiguous {field_name} match for error; candidates: {', '.join(result.candidates)}"
            )

    param_hits = [(rule, field) for rule, field in exact if field == "parameter_key"]
    unique_param_ids = {rule.logical_id for rule, _ in param_hits}
    if len(unique_param_ids) == 1:
        rule = param_hits[0][0]
        result.rule = rule
        result.matched_on = "parameter_key"
        result.candidates = [rule.logical_id]
        return result
    if len(unique_param_ids) > 1:
        result.candidates = sorted(unique_param_ids)
        raise RuleMappingError(
            "Ambiguous parameter-key match for error; "
            f"candidates: {', '.join(result.candidates)}"
        )

    required_parts = extract_required_parameters(error_text)
    if required_parts:
        required = ",".join(required_parts)
        result.tokens = required_parts + [
            t for t in result.tokens if t.lower() not in {p.lower() for p in required_parts}
        ]
        mapped = _map_missing_required_parameter(required, rules)
        if mapped is not None:
            result.rule = mapped
            result.matched_on = "missing_required_parameter"
            result.candidates = [mapped.logical_id]
            return result

    substring_hits: List[Tuple[RuleRef, str]] = []
    for token in tokens:
        if len(token) < 8:
            continue
        token_l = token.lower()
        for rule in rules:
            for field_name, value in (
                ("logical_id", rule.logical_id),
                ("config_rule_name", rule.config_rule_name),
                ("source_identifier", rule.source_identifier),
            ):
                if value and token_l in value.lower():
                    substring_hits.append((rule, field_name))
                    break
    unique_sub = {rule.logical_id for rule, _ in substring_hits}
    if len(unique_sub) == 1:
        rule = substring_hits[0][0]
        result.rule = rule
        result.matched_on = f"substring:{substring_hits[0][1]}"
        result.candidates = [rule.logical_id]
        return result
    if len(unique_sub) > 1:
        result.candidates = sorted(unique_sub)
        raise RuleMappingError(
            f"Ambiguous substring match for error; candidates: {', '.join(result.candidates)}"
        )

    raise RuleMappingError(
        "Could not map deploy error to a single config rule. "
        f"Tokens considered: {', '.join(tokens) or '(none)'}"
    )
