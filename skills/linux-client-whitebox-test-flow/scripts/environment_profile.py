#!/usr/bin/env python3
"""Validate a non-secret, multi-node Linux white-box environment profile."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


PROTECTED_PREFIXES = ("protected:", "provider:", "session:")
FORBIDDEN_SECRET_KEYS = {"password", "passwd", "token", "secret", "privatekey", "private_key", "apikey", "api_key"}


class ProfileError(ValueError):
    pass


def _text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _text_list(value: Any, *, non_empty: bool = False) -> bool:
    return isinstance(value, list) and (not non_empty or bool(value)) and all(_text(item) for item in value)


def _protected_ref(value: Any) -> bool:
    return _text(value) and value.startswith(PROTECTED_PREFIXES)


def _find_forbidden_keys(value: Any, path: str = "") -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}" if path else key
            if str(key).lower() in FORBIDDEN_SECRET_KEYS:
                found.append(child_path)
            found.extend(_find_forbidden_keys(child, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found.extend(_find_forbidden_keys(child, f"{path}[{index}]"))
    return found


def load_profile(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ProfileError(f"profile not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ProfileError(f"invalid JSON at line {exc.lineno}, column {exc.colno}: {exc.msg}") from exc
    if not isinstance(data, dict):
        raise ProfileError("profile root must be an object")
    return data


def validate_profile(data: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if data.get("schemaVersion") != 2:
        errors.append("schemaVersion must be 2")
    for field in ("bindingId", "displayName", "scope", "fingerprint", "toolchainProfile"):
        if not _text(data.get(field)):
            errors.append(f"{field} must be non-empty")
    if not _text_list(data.get("capabilities"), non_empty=True):
        errors.append("capabilities must be a non-empty string array")

    nodes = data.get("nodes")
    node_ids: set[str] = set()
    if not isinstance(nodes, list) or not nodes:
        errors.append("nodes must be a non-empty array")
        nodes = []
    for index, node in enumerate(nodes):
        prefix = f"nodes[{index}]"
        if not isinstance(node, dict):
            errors.append(f"{prefix} must be an object")
            continue
        for field in ("nodeId", "platform", "fingerprint"):
            if not _text(node.get(field)):
                errors.append(f"{prefix}.{field} must be non-empty")
        node_id = node.get("nodeId")
        if _text(node_id) and node_id in node_ids:
            errors.append(f"duplicate nodeId {node_id}")
        if _text(node_id):
            node_ids.add(node_id)
        roles = node.get("roles")
        if not _text_list(roles, non_empty=True):
            errors.append(f"{prefix}.roles must be a non-empty string array")
            roles = []
        if not _text_list(node.get("capabilities"), non_empty=True):
            errors.append(f"{prefix}.capabilities must be a non-empty string array")
        if not _protected_ref(node.get("accessRef")):
            errors.append(f"{prefix}.accessRef must be a protected/provider/session reference")
        privilege_ref = node.get("privilegeRef")
        if privilege_ref is not None and not _protected_ref(privilege_ref):
            errors.append(f"{prefix}.privilegeRef must be null or a protected/provider/session reference")
        credential_refs = node.get("credentialRefs")
        if not isinstance(credential_refs, dict):
            errors.append(f"{prefix}.credentialRefs must be an object")
        else:
            for name, value in credential_refs.items():
                if not _text(name) or not _protected_ref(value):
                    errors.append(f"{prefix}.credentialRefs entries must use named protected/provider/session references")
        commands = node.get("commands")
        if not isinstance(commands, dict):
            errors.append(f"{prefix}.commands must be an object")
        else:
            for field in ("preflight", "cleanup"):
                if not _text(commands.get(field)):
                    errors.append(f"{prefix}.commands.{field} must be non-empty")
            for role, command in (("build", "build"), ("test", "test")):
                if role in roles and not _text(commands.get(command)):
                    errors.append(f"{prefix}.commands.{command} is required for role {role}")

    evidence_policy = data.get("evidencePolicy")
    if not isinstance(evidence_policy, dict):
        errors.append("evidencePolicy must be an object")
    else:
        for field in ("location", "encoding", "decisionFormat", "locale"):
            if not _text(evidence_policy.get(field)):
                errors.append(f"evidencePolicy.{field} must be non-empty")
        if evidence_policy.get("encoding") != "UTF-8":
            errors.append("evidencePolicy.encoding must be UTF-8")
        if evidence_policy.get("decisionFormat") != "JSON":
            errors.append("evidencePolicy.decisionFormat must be JSON")
    if data.get("containsSecrets") is not False:
        errors.append("containsSecrets must be false; store only protected credential references")
    for path in _find_forbidden_keys(data):
        errors.append(f"secret-bearing field is not allowed in a profile: {path}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("validate",))
    parser.add_argument("profile", type=Path)
    args = parser.parse_args()
    try:
        data = load_profile(args.profile)
        errors = validate_profile(data)
    except ProfileError as exc:
        print(json.dumps({"valid": False, "errors": [str(exc)]}, indent=2))
        return 2
    print(json.dumps({"valid": not errors, "errors": errors}, indent=2))
    return 0 if not errors else 2


if __name__ == "__main__":
    sys.exit(main())
