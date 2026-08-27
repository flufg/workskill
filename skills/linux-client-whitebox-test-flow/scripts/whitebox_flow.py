#!/usr/bin/env python3
"""Validate and report progress for a Linux client white-box test run.

This tool is read-only: it never edits a manifest, advances a stage, builds code,
or runs tests.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


STAGES = ("intake", "discovery", "plan", "test_assets", "review", "build", "execution", "report")
STATES = {"PENDING", "IN_PROGRESS", "COMPLETED", "BLOCKED"}
TEST_RESULTS = {"NOT_RUN", "PASS", "FAIL", "ENV_UNAVAILABLE"}
APPROVALS = {"PROCEED", "REWORK", "STOP"}
SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")


class ManifestError(ValueError):
    pass


def _text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _text_list(value: Any, *, non_empty: bool = False) -> bool:
    return isinstance(value, list) and (not non_empty or bool(value)) and all(_text(item) for item in value)


def load_manifest(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ManifestError(f"manifest not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ManifestError(f"invalid JSON at line {exc.lineno}, column {exc.colno}: {exc.msg}") from exc
    if not isinstance(data, dict):
        raise ManifestError("manifest root must be an object")
    return data


def validate_manifest(data: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if data.get("schemaVersion") != 1:
        errors.append("schemaVersion must be 1")
    if not _text(data.get("runId")):
        errors.append("runId must be non-empty")

    target = data.get("target")
    if not isinstance(target, dict):
        errors.append("target must be an object")
    else:
        for field in ("repository", "gitRef", "component", "changeType", "requirementRef", "testRecordRef"):
            if not _text(target.get(field)):
                errors.append(f"target.{field} must be non-empty")
        git_ref = target.get("gitRef")
        if _text(git_ref) and (re.match(r"^[A-Za-z]:[\\/]", git_ref) or git_ref.startswith(("/", "\\")) or "\\" in git_ref):
            errors.append("target.gitRef must be a Git ref, not a filesystem path")
        if target.get("changeType") not in {"feature", "bugfix"}:
            errors.append("target.changeType must be feature or bugfix")

    candidate = data.get("candidate")
    if not isinstance(candidate, dict):
        errors.append("candidate must be an object")
    elif not SHA256_RE.fullmatch(str(candidate.get("sourceManifestSha256", ""))):
        errors.append("candidate.sourceManifestSha256 must be 64 hexadecimal characters")

    environment = data.get("environment")
    if not isinstance(environment, dict):
        errors.append("environment must be an object")
    else:
        for field in ("bindingId", "profile"):
            if not _text(environment.get(field)):
                errors.append(f"environment.{field} must be non-empty")
        if not _text_list(environment.get("capabilities"), non_empty=True):
            errors.append("environment.capabilities must be a non-empty string array")
        if not _text_list(environment.get("evidence"), non_empty=True):
            errors.append("environment.evidence must be a non-empty string array")

    stages = data.get("stages")
    if not isinstance(stages, dict):
        errors.append("stages must be an object")
        return errors

    active: list[str] = []
    for name in STAGES:
        stage = stages.get(name)
        if not isinstance(stage, dict):
            errors.append(f"stages.{name} must be an object")
            continue
        state = stage.get("state")
        if state not in STATES:
            errors.append(f"stages.{name}.state must be one of {sorted(STATES)}")
            continue
        if state in {"IN_PROGRESS", "BLOCKED"}:
            active.append(name)
        if state == "COMPLETED":
            if not _text(stage.get("summary")):
                errors.append(f"completed stage {name} needs a non-empty summary")
            if not _text_list(stage.get("evidence"), non_empty=True):
                errors.append(f"completed stage {name} needs non-empty evidence")
        if state == "BLOCKED":
            if not _text(stage.get("summary")):
                errors.append(f"blocked stage {name} needs a non-empty summary")
            if not _text_list(stage.get("missing"), non_empty=True):
                errors.append(f"blocked stage {name} needs a non-empty missing list")
    if len(active) > 1:
        errors.append(f"at most one stage may be active; found {active}")

    approvals = data.get("approvals", {})
    if not isinstance(approvals, dict):
        errors.append("approvals must be an object")
        approvals = {}
    for stage_name, approval in approvals.items():
        if stage_name not in STAGES:
            errors.append(f"approval references unknown stage {stage_name}")
        elif not isinstance(approval, dict):
            errors.append(f"approvals.{stage_name} must be an object")
        else:
            if approval.get("decision") not in APPROVALS:
                errors.append(f"approvals.{stage_name}.decision must be one of {sorted(APPROVALS)}")
            if stages.get(stage_name, {}).get("state") != "COMPLETED":
                errors.append(f"approval for {stage_name} requires that stage to be COMPLETED")

    for index, name in enumerate(STAGES[1:], start=1):
        stage = stages.get(name, {})
        if stage.get("state") == "PENDING":
            continue
        previous = STAGES[index - 1]
        if stages.get(previous, {}).get("state") != "COMPLETED":
            errors.append(f"stage {name} cannot start before {previous} is COMPLETED")
        if approvals.get(previous, {}).get("decision") != "PROCEED":
            errors.append(f"stage {name} requires explicit PROCEED approval after {previous}")

    review = stages.get("review", {})
    build = stages.get("build", {})
    execution = stages.get("execution", {})
    if review.get("state") == "COMPLETED" and review.get("decision") not in {"PASS", "FAIL"}:
        errors.append("completed review stage needs decision PASS or FAIL")
    for name, stage in (("build", build), ("execution", execution)):
        result = stage.get("result", "NOT_RUN")
        if result not in TEST_RESULTS:
            errors.append(f"stages.{name}.result must be one of {sorted(TEST_RESULTS)}")
        if stage.get("state") == "COMPLETED" and result == "NOT_RUN":
            errors.append(f"completed stage {name} cannot have result NOT_RUN")
    if build.get("state") != "PENDING" and review.get("decision") != "PASS":
        errors.append("build cannot start until review decision is PASS")
    if execution.get("state") != "PENDING" and build.get("result") != "PASS":
        errors.append("execution cannot start until build result is PASS")

    results = data.get("testResults", [])
    if not isinstance(results, list):
        errors.append("testResults must be an array")
    else:
        for index, result in enumerate(results):
            prefix = f"testResults[{index}]"
            if not isinstance(result, dict):
                errors.append(f"{prefix} must be an object")
                continue
            for field in ("id", "layer"):
                if not _text(result.get(field)):
                    errors.append(f"{prefix}.{field} must be non-empty")
            status = result.get("status")
            if status not in TEST_RESULTS:
                errors.append(f"{prefix}.status must be one of {sorted(TEST_RESULTS)}")
            if status in {"PASS", "FAIL"}:
                if not _text(result.get("command")):
                    errors.append(f"{prefix} with {status} needs command")
                if not _text_list(result.get("evidence"), non_empty=True):
                    errors.append(f"{prefix} with {status} needs evidence")
            if status == "ENV_UNAVAILABLE":
                if not _text(result.get("reason")):
                    errors.append(f"{prefix} with ENV_UNAVAILABLE needs reason")
                if not _text_list(result.get("evidence"), non_empty=True):
                    errors.append(f"{prefix} with ENV_UNAVAILABLE needs evidence")
    return errors


def progress(data: dict[str, Any]) -> dict[str, Any]:
    stages = data["stages"]
    approvals = data.get("approvals", {})
    completed = [name for name in STAGES if stages[name]["state"] == "COMPLETED"]
    active = next((name for name in STAGES if stages[name]["state"] in {"IN_PROGRESS", "BLOCKED"}), None)
    if active:
        stage = stages[active]
        return {
            "runId": data["runId"], "currentStage": active, "currentState": stage["state"],
            "completed": completed, "missing": stage.get("missing", []),
            "nextRecommended": f"complete or unblock {active}; then summarize and stop for a decision",
            "stopForUserDecision": stage["state"] == "BLOCKED",
        }

    latest = completed[-1] if completed else None
    if latest:
        stage = stages[latest]
        result = stage.get("result")
        if latest == "review" and stage.get("decision") != "PASS":
            recommendation = "return to test_assets and resolve review findings"
        elif latest == "build" and result != "PASS":
            recommendation = "choose read-only diagnosis, authorized rebuild, rework, or stop"
        elif latest == "execution" and result in {"FAIL", "ENV_UNAVAILABLE"}:
            recommendation = "choose diagnosis/retest, accept and report, or stop"
        elif latest == "report":
            recommendation = "flow complete; do not publish or push automatically"
        else:
            next_index = STAGES.index(latest) + 1
            next_name = STAGES[next_index] if next_index < len(STAGES) else None
            recommendation = f"rework {latest} or authorize {next_name}" if next_name else "flow complete"
        decision = approvals.get(latest, {}).get("decision")
        hard_stop = (latest == "review" and stage.get("decision") != "PASS") or (latest == "build" and result != "PASS")
        if decision != "PROCEED" or latest == "report" or hard_stop:
            return {
                "runId": data["runId"], "currentStage": latest, "currentState": "CHECKPOINT",
                "completed": completed, "missing": stage.get("missing", []),
                "nextRecommended": recommendation, "stopForUserDecision": True,
            }

    pending = next((name for name in STAGES if stages[name]["state"] == "PENDING"), None)
    return {
        "runId": data["runId"], "currentStage": pending or "complete",
        "currentState": "PENDING" if pending else "COMPLETED", "completed": completed,
        "missing": stages[pending].get("missing", []) if pending else [],
        "nextRecommended": f"execute authorized {pending}" if pending else "flow complete; do not publish automatically",
        "stopForUserDecision": not bool(pending),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("validate", "status"))
    parser.add_argument("manifest", type=Path)
    args = parser.parse_args()
    try:
        data = load_manifest(args.manifest)
        errors = validate_manifest(data)
    except ManifestError as exc:
        print(json.dumps({"valid": False, "errors": [str(exc)]}, indent=2))
        return 2
    if errors:
        print(json.dumps({"valid": False, "errors": errors}, indent=2))
        return 2
    output = {"valid": True, "errors": []} if args.command == "validate" else {"valid": True, **progress(data)}
    print(json.dumps(output, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
