#!/usr/bin/env python3
"""Validate a non-secret Linux white-box environment profile."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


class ProfileError(ValueError):
    pass


def _text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _text_list(value: Any, *, non_empty: bool = False) -> bool:
    return isinstance(value, list) and (not non_empty or bool(value)) and all(_text(item) for item in value)


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
    if data.get("schemaVersion") != 1:
        errors.append("schemaVersion must be 1")
    for field in ("bindingId", "displayName", "scope", "fingerprint", "toolchainProfile", "evidencePolicy"):
        if not _text(data.get(field)):
            errors.append(f"{field} must be non-empty")
    if not _text_list(data.get("capabilities"), non_empty=True):
        errors.append("capabilities must be a non-empty string array")
    if not _text_list(data.get("credentialRefs")):
        errors.append("credentialRefs must be a string array")

    platforms = data.get("platforms")
    if not isinstance(platforms, dict):
        errors.append("platforms must be an object")
    else:
        for field in ("build", "test"):
            if not _text(platforms.get(field)):
                errors.append(f"platforms.{field} must be non-empty")

    commands = data.get("commands")
    if not isinstance(commands, dict):
        errors.append("commands must be an object")
    else:
        for field in ("build", "test", "preflight", "cleanup"):
            if not _text(commands.get(field)):
                errors.append(f"commands.{field} must be non-empty")

    if data.get("containsSecrets") is not False:
        errors.append("containsSecrets must be false; store only protected credential references")
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
