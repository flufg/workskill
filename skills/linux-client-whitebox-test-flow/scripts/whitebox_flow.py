#!/usr/bin/env python3
"""Validate, audit, migrate, and report Linux white-box test progress."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any


STAGES = ("intake", "discovery", "plan", "test_assets", "review", "build", "execution", "report")
STATES = {"PENDING", "IN_PROGRESS", "COMPLETED", "BLOCKED"}
TEST_RESULTS = {"NOT_RUN", "PASS", "FAIL", "ENV_UNAVAILABLE"}
RESULT_REASONS = {"PRODUCT", "COMPATIBILITY", "FIXTURE", "INFRA", "ENVIRONMENT"}
APPROVALS = {"PROCEED", "REWORK", "STOP"}
LIFECYCLE_STATES = {"ACTIVE", "REPORTED", "REOPENED", "CLOSED"}
CYCLE_STATES = {"PENDING", "IN_PROGRESS", "COMPLETED", "BLOCKED"}
CYCLE_TYPES = {"INITIAL", "RETEST", "SUPPLEMENTAL"}
BUNDLE_STATES = {"UNRESOLVED", "VERIFIED", "DRIFTED"}
ENVIRONMENT_STATES = {"UNCONFIGURED", "CONFIGURED", "VERIFIED", "DRIFTED", "UNAVAILABLE"}
ENVIRONMENT_PERSISTENCE = {"UNDECIDED", "PRIVATE", "PROJECT", "SESSION"}
AUTHORIZATION_MODES = {"CHECKPOINTED", "CONTINUOUS"}
MANDATORY_PAUSES = {
    "FAILURE", "CANDIDATE_CHANGE", "ENVIRONMENT_DRIFT", "DESTRUCTIVE_ACTION",
    "MISSING_PERMISSION", "CREDENTIAL_UNAVAILABLE", "CLEANUP_FAILURE", "SCOPE_EXPANSION",
}
EVIDENCE_KINDS = {"LOCAL_FILE", "REMOTE_RECEIPT", "COMMAND", "RECORD", "RECORD_INDEX", "SCREENSHOT", "LOG", "REFERENCE"}
COMPATIBILITY_PAIRS = {("OLD", "OLD"), ("OLD", "NEW"), ("NEW", "OLD"), ("NEW", "NEW")}
SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")


class ManifestError(ValueError):
    pass


def _text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _text_list(value: Any, *, non_empty: bool = False) -> bool:
    return isinstance(value, list) and (not non_empty or bool(value)) and all(_text(item) for item in value)


def _sha(value: Any) -> bool:
    return isinstance(value, str) and bool(SHA256_RE.fullmatch(value))


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


def _validate_evidence_list(value: Any, prefix: str, errors: list[str], *, non_empty: bool = False) -> None:
    if not _text_list(value, non_empty=non_empty):
        qualifier = "a non-empty" if non_empty else "a"
        errors.append(f"{prefix} must be {qualifier} string array of evidence IDs")


def _validate_result(result: Any, prefix: str, errors: list[str]) -> None:
    if not isinstance(result, dict):
        errors.append(f"{prefix} must be an object")
        return
    for field in ("id", "layer"):
        if not _text(result.get(field)):
            errors.append(f"{prefix}.{field} must be non-empty")
    status = result.get("status")
    if status not in TEST_RESULTS:
        errors.append(f"{prefix}.status must be one of {sorted(TEST_RESULTS)}")
        return
    evidence = result.get("evidence", [])
    _validate_evidence_list(evidence, f"{prefix}.evidence", errors)
    if status in {"PASS", "FAIL"} and not _text(result.get("command")):
        errors.append(f"{prefix} with {status} needs command")
    if status in {"PASS", "FAIL", "ENV_UNAVAILABLE"}:
        _validate_evidence_list(evidence, f"{prefix}.evidence", errors, non_empty=True)
    if status in {"FAIL", "ENV_UNAVAILABLE"}:
        if result.get("reasonCategory") not in RESULT_REASONS:
            errors.append(f"{prefix}.reasonCategory must be one of {sorted(RESULT_REASONS)} for {status}")
        if not _text(result.get("reason")):
            errors.append(f"{prefix} with {status} needs reason")
    if status == "NOT_RUN" and not _text(result.get("reason")):
        errors.append(f"{prefix} with NOT_RUN needs reason")
    if "scenarioOutcome" in result and not _text(result.get("scenarioOutcome")):
        errors.append(f"{prefix}.scenarioOutcome must be non-empty when present")


def _transition_authorized(data: dict[str, Any], previous: str, current: str) -> bool:
    approvals = data.get("approvals", {})
    if isinstance(approvals, dict) and approvals.get(previous, {}).get("decision") == "PROCEED":
        return True
    authorization = data.get("authorization", {})
    return (
        isinstance(authorization, dict)
        and authorization.get("mode") == "CONTINUOUS"
        and previous in authorization.get("scope", [])
        and current in authorization.get("scope", [])
        and _text(authorization.get("grantId"))
    )


def validate_manifest(data: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if data.get("schemaVersion") != 2:
        errors.append("schemaVersion must be 2; migrate schemaVersion 1 with the migrate command")
    if not _text(data.get("runId")):
        errors.append("runId must be non-empty")

    lifecycle = data.get("lifecycle")
    lifecycle_state = None
    if not isinstance(lifecycle, dict):
        errors.append("lifecycle must be an object")
    else:
        lifecycle_state = lifecycle.get("state")
        if lifecycle_state not in LIFECYCLE_STATES:
            errors.append(f"lifecycle.state must be one of {sorted(LIFECYCLE_STATES)}")
        if not isinstance(lifecycle.get("revision"), int) or lifecycle.get("revision", 0) < 1:
            errors.append("lifecycle.revision must be a positive integer")
        if lifecycle_state == "REOPENED" and not _text(lifecycle.get("reopenReason")):
            errors.append("REOPENED lifecycle needs reopenReason")
        if lifecycle_state == "CLOSED" and not _text(lifecycle.get("closedAt")):
            errors.append("CLOSED lifecycle needs closedAt")

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
        if target.get("changeType") not in {"feature", "bugfix", "upgrade", "maintenance"}:
            errors.append("target.changeType must be feature, bugfix, upgrade, or maintenance")

    bundle = data.get("releaseBundle")
    bundle_state = None
    known_bundle_ids: set[str] = set()
    if not isinstance(bundle, dict):
        errors.append("releaseBundle must be an object")
    else:
        bundle_state = bundle.get("state")
        if bundle_state not in BUNDLE_STATES:
            errors.append(f"releaseBundle.state must be one of {sorted(BUNDLE_STATES)}")
        _validate_evidence_list(bundle.get("evidence"), "releaseBundle.evidence", errors)
        if bundle_state == "VERIFIED":
            for field in ("bundleId", "bundleSha256"):
                if field == "bundleSha256" and not _sha(bundle.get(field)):
                    errors.append("releaseBundle.bundleSha256 must be 64 hexadecimal characters when VERIFIED")
                elif field == "bundleId" and not _text(bundle.get(field)):
                    errors.append("releaseBundle.bundleId must be non-empty when VERIFIED")
            if _text(bundle.get("bundleId")):
                known_bundle_ids.add(bundle["bundleId"])
            _validate_evidence_list(bundle.get("evidence"), "releaseBundle.evidence", errors, non_empty=True)
            components = bundle.get("components")
            if not isinstance(components, list) or not components:
                errors.append("releaseBundle.components must be non-empty when VERIFIED")
            else:
                names: set[str] = set()
                for index, component in enumerate(components):
                    prefix = f"releaseBundle.components[{index}]"
                    if not isinstance(component, dict):
                        errors.append(f"{prefix} must be an object")
                        continue
                    for field in ("name", "role"):
                        if not _text(component.get(field)):
                            errors.append(f"{prefix}.{field} must be non-empty")
                    name = component.get("name")
                    if _text(name) and name in names:
                        errors.append(f"duplicate release component name {name}")
                    if _text(name):
                        names.add(name)
                    source_sha = component.get("sourceManifestSha256")
                    artifact_sha = component.get("artifactSha256")
                    if source_sha is not None and not _sha(source_sha):
                        errors.append(f"{prefix}.sourceManifestSha256 must be null or 64 hexadecimal characters")
                    if artifact_sha is not None and not _sha(artifact_sha):
                        errors.append(f"{prefix}.artifactSha256 must be null or 64 hexadecimal characters")
                    if source_sha is None and artifact_sha is None:
                        errors.append(f"{prefix} needs sourceManifestSha256 or artifactSha256")
        elif bundle_state == "DRIFTED" and not _text(bundle.get("reason")):
            errors.append("DRIFTED releaseBundle needs reason")
        if bundle_state == "DRIFTED" and _text(bundle.get("bundleId")):
            known_bundle_ids.add(bundle["bundleId"])

    bundle_history = data.get("releaseBundleHistory")
    if not isinstance(bundle_history, list):
        errors.append("releaseBundleHistory must be an array")
        bundle_history = []
    for index, historical in enumerate(bundle_history):
        prefix = f"releaseBundleHistory[{index}]"
        if not isinstance(historical, dict):
            errors.append(f"{prefix} must be an object")
            continue
        bundle_id = historical.get("bundleId")
        if not _text(bundle_id):
            errors.append(f"{prefix}.bundleId must be non-empty")
        elif bundle_id in known_bundle_ids:
            errors.append(f"duplicate release bundle ID {bundle_id}")
        else:
            known_bundle_ids.add(bundle_id)
        if historical.get("state") != "VERIFIED":
            errors.append(f"{prefix}.state must remain VERIFIED")
        if not _sha(historical.get("bundleSha256")):
            errors.append(f"{prefix}.bundleSha256 must be 64 hexadecimal characters")
        components = historical.get("components")
        if not isinstance(components, list) or not components:
            errors.append(f"{prefix}.components must be non-empty")
        else:
            for component_index, component in enumerate(components):
                component_prefix = f"{prefix}.components[{component_index}]"
                if not isinstance(component, dict) or not _text(component.get("name")) or not _text(component.get("role")):
                    errors.append(f"{component_prefix} needs name and role")
                    continue
                if component.get("sourceManifestSha256") is None and component.get("artifactSha256") is None:
                    errors.append(f"{component_prefix} needs sourceManifestSha256 or artifactSha256")
                for field in ("sourceManifestSha256", "artifactSha256"):
                    if component.get(field) is not None and not _sha(component.get(field)):
                        errors.append(f"{component_prefix}.{field} must be null or 64 hexadecimal characters")
        _validate_evidence_list(historical.get("evidence"), f"{prefix}.evidence", errors, non_empty=True)

    environment = data.get("environment")
    environment_state = None
    if not isinstance(environment, dict):
        errors.append("environment must be an object")
    else:
        environment_state = environment.get("state")
        persistence = environment.get("persistence")
        if environment_state not in ENVIRONMENT_STATES:
            errors.append(f"environment.state must be one of {sorted(ENVIRONMENT_STATES)}")
        if persistence not in ENVIRONMENT_PERSISTENCE:
            errors.append(f"environment.persistence must be one of {sorted(ENVIRONMENT_PERSISTENCE)}")
        for field in ("nodeIds", "capabilities", "evidence"):
            _validate_evidence_list(environment.get(field), f"environment.{field}", errors)
        configured_states = {"CONFIGURED", "VERIFIED", "DRIFTED", "UNAVAILABLE"}
        if environment_state in configured_states:
            for field in ("bindingId", "profileRef", "fingerprint"):
                if not _text(environment.get(field)):
                    errors.append(f"environment.{field} must be non-empty when state is {environment_state}")
            if persistence == "UNDECIDED":
                errors.append(f"environment.persistence cannot be UNDECIDED when state is {environment_state}")
        if environment_state in {"CONFIGURED", "VERIFIED"}:
            _validate_evidence_list(environment.get("capabilities"), "environment.capabilities", errors, non_empty=True)
            _validate_evidence_list(environment.get("evidence"), "environment.evidence", errors, non_empty=True)
        if environment_state == "VERIFIED":
            observed = environment.get("observedFingerprint")
            if not _text(observed):
                errors.append("environment.observedFingerprint must be non-empty when state is VERIFIED")
            elif observed != environment.get("fingerprint"):
                errors.append("VERIFIED environment requires matching fingerprint and observedFingerprint")
        if environment_state in {"DRIFTED", "UNAVAILABLE"} and not _text(environment.get("reason")):
            errors.append(f"environment.reason must be non-empty when state is {environment_state}")

    authorization = data.get("authorization")
    if not isinstance(authorization, dict):
        errors.append("authorization must be an object")
    else:
        mode = authorization.get("mode")
        if mode not in AUTHORIZATION_MODES:
            errors.append(f"authorization.mode must be one of {sorted(AUTHORIZATION_MODES)}")
        if not _text_list(authorization.get("scope")):
            errors.append("authorization.scope must be a string array")
        pause_on = authorization.get("pauseOn")
        if not _text_list(pause_on):
            errors.append("authorization.pauseOn must be a string array")
        if mode == "CONTINUOUS":
            for field in ("grantId", "grantedAt"):
                if not _text(authorization.get(field)):
                    errors.append(f"CONTINUOUS authorization needs {field}")
            unknown_scope = set(authorization.get("scope", [])) - set(STAGES)
            if unknown_scope:
                errors.append(f"authorization.scope contains unknown stages {sorted(unknown_scope)}")
            missing_pauses = MANDATORY_PAUSES - set(pause_on or [])
            if missing_pauses:
                errors.append(f"CONTINUOUS authorization.pauseOn is missing {sorted(missing_pauses)}")

    evidence_index = data.get("evidenceIndex")
    evidence_ids: set[str] = set()
    if not isinstance(evidence_index, list):
        errors.append("evidenceIndex must be an array")
        evidence_index = []
    for index, item in enumerate(evidence_index):
        prefix = f"evidenceIndex[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{prefix} must be an object")
            continue
        evidence_id = item.get("id")
        if not _text(evidence_id):
            errors.append(f"{prefix}.id must be non-empty")
        elif evidence_id in evidence_ids:
            errors.append(f"duplicate evidence ID {evidence_id}")
        else:
            evidence_ids.add(evidence_id)
        if item.get("kind") not in EVIDENCE_KINDS:
            errors.append(f"{prefix}.kind must be one of {sorted(EVIDENCE_KINDS)}")
        if not _text(item.get("ref")):
            errors.append(f"{prefix}.ref must be non-empty")
        if item.get("kind") in {"LOCAL_FILE", "RECORD_INDEX"} and not _sha(item.get("sha256")):
            errors.append(f"{prefix}.sha256 is required for local evidence")
        if item.get("kind") == "REMOTE_RECEIPT" and not _text(item.get("verifiedAt")):
            errors.append(f"{prefix}.verifiedAt is required for REMOTE_RECEIPT")
        if item.get("kind") == "REMOTE_RECEIPT" and item.get("validationStatus") not in {"VALID", "STALE", "UNAVAILABLE"}:
            errors.append(f"{prefix}.validationStatus must be VALID, STALE, or UNAVAILABLE for REMOTE_RECEIPT")
        if "encoding" in item and item.get("encoding") not in {"UTF-8", "BINARY"}:
            errors.append(f"{prefix}.encoding must be UTF-8 or BINARY")

    referenced_evidence: list[tuple[str, list[str]]] = []
    if isinstance(bundle, dict):
        referenced_evidence.append(("releaseBundle.evidence", bundle.get("evidence", [])))
    for index, historical in enumerate(bundle_history):
        if isinstance(historical, dict):
            referenced_evidence.append((f"releaseBundleHistory[{index}].evidence", historical.get("evidence", [])))
    if isinstance(environment, dict):
        referenced_evidence.append(("environment.evidence", environment.get("evidence", [])))

    stages = data.get("stages")
    active: list[str] = []
    if not isinstance(stages, dict):
        errors.append("stages must be an object")
        stages = {}
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
        _validate_evidence_list(stage.get("evidence"), f"stages.{name}.evidence", errors)
        referenced_evidence.append((f"stages.{name}.evidence", stage.get("evidence", [])))
        if state == "COMPLETED":
            if not _text(stage.get("summary")):
                errors.append(f"completed stage {name} needs a non-empty summary")
            _validate_evidence_list(stage.get("evidence"), f"stages.{name}.evidence", errors, non_empty=True)
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
        if not _transition_authorized(data, previous, name):
            errors.append(f"stage {name} needs PROCEED or a matching CONTINUOUS authorization after {previous}")

    review = stages.get("review", {})
    build = stages.get("build", {})
    execution = stages.get("execution", {})
    report = stages.get("report", {})
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

    cycles = data.get("executionCycles")
    cycle_ids: set[str] = set()
    completed_cycle_ids: set[str] = set()
    if not isinstance(cycles, list):
        errors.append("executionCycles must be an array")
        cycles = []
    for index, cycle in enumerate(cycles):
        prefix = f"executionCycles[{index}]"
        if not isinstance(cycle, dict):
            errors.append(f"{prefix} must be an object")
            continue
        cycle_id = cycle.get("cycleId")
        if not _text(cycle_id):
            errors.append(f"{prefix}.cycleId must be non-empty")
        elif cycle_id in cycle_ids:
            errors.append(f"duplicate cycle ID {cycle_id}")
        else:
            cycle_ids.add(cycle_id)
        if cycle.get("type") not in CYCLE_TYPES:
            errors.append(f"{prefix}.type must be one of {sorted(CYCLE_TYPES)}")
        status = cycle.get("status")
        if status not in CYCLE_STATES:
            errors.append(f"{prefix}.status must be one of {sorted(CYCLE_STATES)}")
        for field in ("releaseBundleId", "environmentBindingId", "environmentFingerprint", "reason"):
            if not _text(cycle.get(field)):
                errors.append(f"{prefix}.{field} must be non-empty")
        if cycle.get("releaseBundleId") not in known_bundle_ids:
            errors.append(f"{prefix}.releaseBundleId is not present in the current or historical release bundles")
        if status in {"PENDING", "IN_PROGRESS", "BLOCKED"} and isinstance(bundle, dict) and bundle_state == "VERIFIED" and cycle.get("releaseBundleId") != bundle.get("bundleId"):
            errors.append(f"active {prefix}.releaseBundleId must match the current verified releaseBundle")
        if cycle.get("result") not in TEST_RESULTS:
            errors.append(f"{prefix}.result must be one of {sorted(TEST_RESULTS)}")
        if not isinstance(cycle.get("cleanupVerified"), bool):
            errors.append(f"{prefix}.cleanupVerified must be boolean")
        _validate_evidence_list(cycle.get("evidence"), f"{prefix}.evidence", errors)
        referenced_evidence.append((f"{prefix}.evidence", cycle.get("evidence", [])))
        test_results = cycle.get("testResults")
        if not isinstance(test_results, list):
            errors.append(f"{prefix}.testResults must be an array")
            test_results = []
        for result_index, result in enumerate(test_results):
            _validate_result(result, f"{prefix}.testResults[{result_index}]", errors)
            if isinstance(result, dict):
                referenced_evidence.append((f"{prefix}.testResults[{result_index}].evidence", result.get("evidence", [])))
        if status == "COMPLETED":
            if _text(cycle_id):
                completed_cycle_ids.add(cycle_id)
            if cycle.get("result") == "NOT_RUN":
                errors.append(f"completed {prefix} cannot have result NOT_RUN")
            if not _text(cycle.get("startedAt")) or not _text(cycle.get("completedAt")):
                errors.append(f"completed {prefix} needs startedAt and completedAt")
            if not test_results:
                errors.append(f"completed {prefix} needs testResults")
            _validate_evidence_list(cycle.get("evidence"), f"{prefix}.evidence", errors, non_empty=True)
        if status == "BLOCKED" and not _text_list(cycle.get("missing"), non_empty=True):
            errors.append(f"blocked {prefix} needs a non-empty missing list")

    revisions = data.get("reportRevisions")
    covered_cycles: set[str] = set()
    revision_numbers: list[int] = []
    batch_ids: set[str] = set()
    if not isinstance(revisions, list):
        errors.append("reportRevisions must be an array")
        revisions = []
    for index, revision in enumerate(revisions):
        prefix = f"reportRevisions[{index}]"
        if not isinstance(revision, dict):
            errors.append(f"{prefix} must be an object")
            continue
        number = revision.get("revision")
        if not isinstance(number, int) or number < 1:
            errors.append(f"{prefix}.revision must be a positive integer")
        else:
            revision_numbers.append(number)
        for field in ("createdAt", "testRecordBatchId", "summary"):
            if not _text(revision.get(field)):
                errors.append(f"{prefix}.{field} must be non-empty")
        batch_id = revision.get("testRecordBatchId")
        if _text(batch_id) and batch_id in batch_ids:
            errors.append(f"duplicate testRecordBatchId {batch_id}")
        if _text(batch_id):
            batch_ids.add(batch_id)
        covered = revision.get("coveredCycles")
        if not _text_list(covered):
            errors.append(f"{prefix}.coveredCycles must be a string array")
        else:
            for cycle_id in covered:
                if cycle_id not in cycle_ids:
                    errors.append(f"{prefix} references unknown cycle {cycle_id}")
                covered_cycles.add(cycle_id)
        _validate_evidence_list(revision.get("testRecordEvidence"), f"{prefix}.testRecordEvidence", errors, non_empty=True)
        referenced_evidence.append((f"{prefix}.testRecordEvidence", revision.get("testRecordEvidence", [])))
    if revision_numbers and revision_numbers != list(range(1, len(revision_numbers) + 1)):
        errors.append("reportRevisions.revision values must be consecutive and ordered from 1")

    scope = data.get("scope")
    compatibility_required = isinstance(scope, dict) and scope.get("compatibility") is True
    matrix = data.get("compatibilityMatrix")
    observed_pairs: set[tuple[str, str]] = set()
    if not isinstance(matrix, list):
        errors.append("compatibilityMatrix must be an array")
        matrix = []
    for index, entry in enumerate(matrix):
        prefix = f"compatibilityMatrix[{index}]"
        if not isinstance(entry, dict):
            errors.append(f"{prefix} must be an object")
            continue
        if not _text(entry.get("id")):
            errors.append(f"{prefix}.id must be non-empty")
        pair = (entry.get("producer"), entry.get("consumer"))
        if pair not in COMPATIBILITY_PAIRS:
            errors.append(f"{prefix} producer/consumer must be OLD or NEW")
        else:
            observed_pairs.add(pair)
        if entry.get("status") not in TEST_RESULTS:
            errors.append(f"{prefix}.status must be one of {sorted(TEST_RESULTS)}")
        _validate_evidence_list(entry.get("evidence"), f"{prefix}.evidence", errors)
        referenced_evidence.append((f"{prefix}.evidence", entry.get("evidence", [])))
        if entry.get("status") in {"PASS", "FAIL", "ENV_UNAVAILABLE"}:
            _validate_evidence_list(entry.get("evidence"), f"{prefix}.evidence", errors, non_empty=True)
        if entry.get("status") in {"FAIL", "ENV_UNAVAILABLE"} and entry.get("reasonCategory") not in RESULT_REASONS:
            errors.append(f"{prefix}.reasonCategory must be one of {sorted(RESULT_REASONS)}")
    if compatibility_required and observed_pairs != COMPATIBILITY_PAIRS:
        errors.append("compatibilityMatrix must contain OLD/OLD, OLD/NEW, NEW/OLD, and NEW/NEW")

    for prefix, references in referenced_evidence:
        if isinstance(references, list):
            for evidence_id in references:
                if _text(evidence_id) and evidence_id not in evidence_ids:
                    errors.append(f"{prefix} references unknown evidence ID {evidence_id}")

    record_index_evidence = data.get("testRecordIndexEvidence")
    if record_index_evidence is not None and not _text(record_index_evidence):
        errors.append("testRecordIndexEvidence must be null or an evidence ID")
    if _text(record_index_evidence) and record_index_evidence not in evidence_ids:
        errors.append(f"testRecordIndexEvidence references unknown evidence ID {record_index_evidence}")

    if lifecycle_state in {"REPORTED", "CLOSED"}:
        if report.get("state") != "COMPLETED":
            errors.append(f"{lifecycle_state} lifecycle requires completed report stage")
        if not revisions:
            errors.append(f"{lifecycle_state} lifecycle requires at least one reportRevision")
        if not _text(record_index_evidence):
            errors.append(f"{lifecycle_state} lifecycle requires testRecordIndexEvidence")
        missing_coverage = completed_cycle_ids - covered_cycles
        if missing_coverage:
            errors.append(f"{lifecycle_state} lifecycle has unreported cycles {sorted(missing_coverage)}")
    if lifecycle_state == "REOPENED":
        if report.get("state") != "COMPLETED":
            errors.append("REOPENED lifecycle requires a previously completed report stage")
        if not (cycle_ids - covered_cycles):
            errors.append("REOPENED lifecycle needs at least one new unreported execution cycle")
    if lifecycle_state == "ACTIVE" and report.get("state") == "COMPLETED":
        errors.append("completed report stage requires lifecycle REPORTED, REOPENED, or CLOSED")
    if lifecycle_state == "CLOSED" and (active or any(c.get("status") in {"PENDING", "IN_PROGRESS", "BLOCKED"} for c in cycles if isinstance(c, dict))):
        errors.append("CLOSED lifecycle cannot have active stages or execution cycles")
    if lifecycle_state == "CLOSED" and any(
        c.get("status") == "COMPLETED" and c.get("cleanupVerified") is not True
        for c in cycles if isinstance(c, dict)
    ):
        errors.append("CLOSED lifecycle requires successful cleanup readback for every completed cycle")
    if execution.get("state") == "COMPLETED" and not completed_cycle_ids:
        errors.append("completed execution stage requires at least one completed executionCycle")
    return errors


def _continuous(data: dict[str, Any], previous: str | None = None, current: str | None = None) -> bool:
    authorization = data.get("authorization", {})
    if authorization.get("mode") != "CONTINUOUS":
        return False
    scope = authorization.get("scope", [])
    return previous in scope and current in scope if previous and current else True


def progress(data: dict[str, Any]) -> dict[str, Any]:
    stages = data["stages"]
    completed = [name for name in STAGES if stages[name]["state"] == "COMPLETED"]
    lifecycle = data["lifecycle"]["state"]
    environment = data["environment"]
    environment_state = environment["state"]
    bundle = data["releaseBundle"]

    if lifecycle == "CLOSED":
        return {
            "runId": data["runId"], "currentStage": "closed", "currentState": "CLOSED",
            "completed": completed, "missing": [],
            "nextRecommended": "start a new run or explicitly reopen this run for supplemental testing",
            "stopForUserDecision": True,
        }
    if environment_state == "UNCONFIGURED":
        return {
            "runId": data["runId"], "currentStage": "environment_setup", "currentState": "BLOCKED",
            "completed": completed, "missing": ["matching environment profile", "user persistence decision"],
            "nextRecommended": "configure an environment profile and choose PRIVATE, PROJECT, or SESSION persistence",
            "stopForUserDecision": True,
        }
    if environment_state == "CONFIGURED":
        return {
            "runId": data["runId"], "currentStage": "environment_preflight", "currentState": "PENDING",
            "completed": completed, "missing": ["read-only environment identity and capability preflight"],
            "nextRecommended": "run the profile preflight and mark VERIFIED only when identity and capabilities match",
            "stopForUserDecision": False,
        }
    if environment_state in {"DRIFTED", "UNAVAILABLE"}:
        return {
            "runId": data["runId"], "currentStage": "environment_setup", "currentState": "BLOCKED",
            "completed": completed, "missing": [environment.get("reason", environment_state)],
            "nextRecommended": "restore, replace, save, or stop using the observed environment",
            "stopForUserDecision": True,
        }
    if bundle["state"] == "UNRESOLVED":
        return {
            "runId": data["runId"], "currentStage": "candidate_setup", "currentState": "BLOCKED",
            "completed": completed, "missing": ["verified release bundle and component identities"],
            "nextRecommended": "record every required release component and verify the bundle identity",
            "stopForUserDecision": True,
        }
    if bundle["state"] == "DRIFTED":
        return {
            "runId": data["runId"], "currentStage": "candidate_setup", "currentState": "BLOCKED",
            "completed": completed, "missing": [bundle.get("reason", "release bundle drift")],
            "nextRecommended": "authorize the new bundle or restore the bound candidate before continuing",
            "stopForUserDecision": True,
        }

    covered = {cycle_id for revision in data["reportRevisions"] for cycle_id in revision["coveredCycles"]}
    unreported = [cycle for cycle in data["executionCycles"] if cycle["cycleId"] not in covered]
    if lifecycle == "REOPENED":
        active_cycle = next((cycle for cycle in unreported if cycle["status"] in {"IN_PROGRESS", "BLOCKED"}), None)
        pending_cycle = next((cycle for cycle in unreported if cycle["status"] == "PENDING"), None)
        failed_cycle = next((
            cycle for cycle in unreported
            if cycle["status"] == "COMPLETED"
            and (cycle.get("result") in {"FAIL", "ENV_UNAVAILABLE"} or cycle.get("cleanupVerified") is not True)
        ), None)
        if failed_cycle:
            return {
                "runId": data["runId"], "currentStage": "execution", "currentState": "CHECKPOINT",
                "currentCycle": failed_cycle["cycleId"], "completed": completed, "missing": failed_cycle.get("missing", []),
                "nextRecommended": "diagnose the failed supplemental cycle, authorize a retest, accept and report, or stop",
                "stopForUserDecision": True,
            }
        if active_cycle or pending_cycle:
            cycle = active_cycle or pending_cycle
            hard_stop = cycle["status"] == "BLOCKED" or cycle.get("result") in {"FAIL", "ENV_UNAVAILABLE"} or cycle.get("cleanupVerified") is False and cycle["status"] == "COMPLETED"
            return {
                "runId": data["runId"], "currentStage": "execution", "currentState": cycle["status"],
                "currentCycle": cycle["cycleId"], "completed": completed, "missing": cycle.get("missing", []),
                "nextRecommended": "complete the supplemental execution cycle and collect evidence",
                "stopForUserDecision": hard_stop,
            }
        return {
            "runId": data["runId"], "currentStage": "report", "currentState": "PENDING",
            "completed": completed, "missing": [],
            "nextRecommended": "append a report revision covering every completed supplemental cycle",
            "stopForUserDecision": not _continuous(data, "execution", "report"),
        }
    if lifecycle == "REPORTED":
        return {
            "runId": data["runId"], "currentStage": "report", "currentState": "REPORTED",
            "completed": completed, "missing": [],
            "nextRecommended": "close the run or explicitly reopen it for a supplemental or retest cycle",
            "stopForUserDecision": True,
        }

    active = next((name for name in STAGES if stages[name]["state"] in {"IN_PROGRESS", "BLOCKED"}), None)
    if active:
        stage = stages[active]
        current_cycle = None
        hard_pause = stage["state"] == "BLOCKED"
        if active == "execution" and data["executionCycles"]:
            current_cycle = data["executionCycles"][-1]
            hard_pause = hard_pause or current_cycle.get("status") == "BLOCKED" or current_cycle.get("result") in {"FAIL", "ENV_UNAVAILABLE"}
            hard_pause = hard_pause or (current_cycle.get("status") == "COMPLETED" and current_cycle.get("cleanupVerified") is not True)
        return {
            "runId": data["runId"], "currentStage": active, "currentState": stage["state"],
            "currentCycle": current_cycle.get("cycleId") if current_cycle else None,
            "completed": completed, "missing": stage.get("missing", []),
            "nextRecommended": f"complete or unblock {active}",
            "stopForUserDecision": hard_pause,
        }

    latest = completed[-1] if completed else None
    if latest:
        stage = stages[latest]
        result = stage.get("result")
        hard_stop = (
            (latest == "review" and stage.get("decision") != "PASS")
            or (latest == "build" and result != "PASS")
            or (latest == "execution" and result in {"FAIL", "ENV_UNAVAILABLE"})
        )
        next_index = STAGES.index(latest) + 1
        next_name = STAGES[next_index] if next_index < len(STAGES) else None
        if hard_stop or (next_name and not _transition_authorized(data, latest, next_name)):
            return {
                "runId": data["runId"], "currentStage": latest, "currentState": "CHECKPOINT",
                "completed": completed, "missing": stage.get("missing", []),
                "nextRecommended": "diagnose, rework, explicitly proceed, or stop" if hard_stop else f"rework {latest} or authorize {next_name}",
                "stopForUserDecision": True,
            }

    pending = next((name for name in STAGES if stages[name]["state"] == "PENDING"), None)
    return {
        "runId": data["runId"], "currentStage": pending or "complete",
        "currentState": "PENDING" if pending else "COMPLETED", "completed": completed,
        "missing": stages[pending].get("missing", []) if pending else [],
        "nextRecommended": f"execute authorized {pending}" if pending else "set lifecycle to REPORTED and append a report revision",
        "stopForUserDecision": False if pending else True,
    }


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def audit_manifest(data: dict[str, Any], manifest_path: Path) -> dict[str, Any]:
    errors = validate_manifest(data)
    warnings: list[str] = []
    checked_files: list[str] = []
    if errors:
        return {"valid": False, "errors": errors, "warnings": warnings, "checkedFiles": checked_files}

    evidence_by_id = {item["id"]: item for item in data["evidenceIndex"]}
    resolved_local: dict[str, Path] = {}
    for item in data["evidenceIndex"]:
        kind = item["kind"]
        if kind in {"LOCAL_FILE", "RECORD_INDEX"}:
            evidence_path = Path(item["ref"])
            if not evidence_path.is_absolute():
                evidence_path = manifest_path.parent / evidence_path
            evidence_path = evidence_path.resolve()
            if not evidence_path.is_file():
                errors.append(f"local evidence missing: {item['id']} -> {evidence_path}")
                continue
            actual = _file_sha256(evidence_path)
            checked_files.append(str(evidence_path))
            resolved_local[item["id"]] = evidence_path
            if actual.lower() != item["sha256"].lower():
                errors.append(f"local evidence hash mismatch: {item['id']}")
        elif kind == "REMOTE_RECEIPT" and item.get("validationStatus") != "VALID":
            errors.append(f"remote evidence is not valid: {item['id']} ({item['ref']})")
        elif kind == "REFERENCE":
            warnings.append(f"legacy reference has no local hash validation: {item['id']} ({item['ref']})")

    completed_cycles = {cycle["cycleId"] for cycle in data["executionCycles"] if cycle["status"] == "COMPLETED"}
    covered_cycles = {cycle_id for revision in data["reportRevisions"] for cycle_id in revision["coveredCycles"]}
    unreported = completed_cycles - covered_cycles
    if data["stages"]["report"]["state"] == "COMPLETED" and unreported:
        errors.append(f"test record is behind the manifest; unreported cycles: {sorted(unreported)}")
    for cycle in data["executionCycles"]:
        if cycle["status"] == "COMPLETED" and not cycle["cleanupVerified"]:
            errors.append(f"completed cycle has no successful cleanup readback: {cycle['cycleId']}")

    record_index_id = data.get("testRecordIndexEvidence")
    record_item = evidence_by_id.get(record_index_id)
    if record_item and record_item.get("kind") == "RECORD_INDEX" and record_index_id in resolved_local:
        try:
            record_index = json.loads(resolved_local[record_index_id].read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            errors.append(f"cannot read structured test record index {record_index_id}: {exc}")
        else:
            if record_index.get("schemaVersion") != 1:
                errors.append("test record index schemaVersion must be 1")
            if record_index.get("runId") != data["runId"]:
                errors.append("test record index runId does not match the manifest")
            if record_index.get("requirementRef") != data["target"]["requirementRef"]:
                errors.append("test record index requirementRef does not match the manifest")
            manifest_batches = {
                (revision["revision"], revision["testRecordBatchId"], tuple(sorted(revision["coveredCycles"])))
                for revision in data["reportRevisions"]
            }
            record_batches: set[tuple[int, str, tuple[str, ...]]] = set()
            record_revisions = record_index.get("reportRevisions")
            if not isinstance(record_revisions, list):
                errors.append("test record index reportRevisions must be an array")
                record_revisions = []
            for index, revision in enumerate(record_revisions):
                if not isinstance(revision, dict):
                    errors.append(f"test record index reportRevisions[{index}] must be an object")
                    continue
                number = revision.get("revision")
                batch_id = revision.get("testRecordBatchId")
                cycles = revision.get("coveredCycles")
                if not isinstance(number, int) or number < 1 or not _text(batch_id) or not _text_list(cycles):
                    errors.append(f"test record index reportRevisions[{index}] is malformed")
                    continue
                record_batches.add((number, batch_id, tuple(sorted(cycles))))
            if record_batches - manifest_batches:
                errors.append(f"manifest is behind the test record index: {sorted(record_batches - manifest_batches)}")
            if manifest_batches - record_batches:
                errors.append(f"test record index is behind the manifest: {sorted(manifest_batches - record_batches)}")
    elif record_item:
        warnings.append("testRecordIndexEvidence is legacy/unstructured; document-to-manifest comparison was skipped")
    if data["lifecycle"]["state"] == "CLOSED" and warnings:
        errors.append("CLOSED audit has unresolved warnings; replace legacy or unverifiable evidence before formal close")
    return {
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "checkedFiles": checked_files,
        "completedCycles": sorted(completed_cycles),
        "reportedCycles": sorted(covered_cycles),
    }


def migrate_v1(data: dict[str, Any]) -> dict[str, Any]:
    if data.get("schemaVersion") != 1:
        raise ManifestError("migrate accepts only schemaVersion 1 manifests")
    if not _text(data.get("runId")):
        raise ManifestError("schemaVersion 1 manifest needs runId")
    candidate = data.get("candidate", {})
    source_sha = candidate.get("sourceManifestSha256")
    if not _sha(source_sha):
        raise ManifestError("schemaVersion 1 candidate.sourceManifestSha256 is invalid")

    migrated = json.loads(json.dumps(data))
    evidence_index: list[dict[str, Any]] = []
    evidence_map: dict[str, str] = {}

    def evidence_ids(refs: Any) -> list[str]:
        if not isinstance(refs, list):
            return []
        ids: list[str] = []
        for ref in refs:
            if not _text(ref):
                continue
            if ref not in evidence_map:
                evidence_id = f"migrated-evidence-{len(evidence_index) + 1:03d}"
                evidence_map[ref] = evidence_id
                evidence_index.append({"id": evidence_id, "kind": "REFERENCE", "ref": ref, "encoding": "UTF-8"})
            ids.append(evidence_map[ref])
        return ids

    for stage in migrated.get("stages", {}).values():
        if isinstance(stage, dict):
            stage["evidence"] = evidence_ids(stage.get("evidence", []))
    environment = migrated.get("environment", {})
    environment["evidence"] = evidence_ids(environment.get("evidence", []))
    environment["nodeIds"] = environment.get("nodeIds", [])

    component = migrated.get("target", {}).get("component", "migrated-primary-component")
    bundle_id = f"migrated-{migrated['runId']}-bundle"
    old_intake = data.get("stages", {}).get("intake", {})
    bundle_evidence = evidence_ids(old_intake.get("evidence", []))
    bundle_state = "VERIFIED" if old_intake.get("state") == "COMPLETED" and bundle_evidence else "UNRESOLVED"
    migrated["releaseBundle"] = {
        "state": bundle_state, "bundleId": bundle_id, "bundleSha256": source_sha,
        "components": [{
            "name": component, "role": "primary", "gitCommit": candidate.get("gitCommit"),
            "sourceManifestSha256": source_sha, "artifactSha256": None,
        }],
        "evidence": bundle_evidence,
        "reason": "migrated from schemaVersion 1",
    }
    migrated["releaseBundleHistory"] = []
    migrated.pop("candidate", None)
    migrated["authorization"] = {
        "mode": "CHECKPOINTED", "grantId": None, "grantedAt": None, "scope": [],
        "pauseOn": sorted(MANDATORY_PAUSES),
    }
    migrated.setdefault("scope", {})["compatibility"] = False
    migrated["compatibilityMatrix"] = []

    old_results = migrated.pop("testResults", [])
    for result in old_results:
        if isinstance(result, dict):
            result["evidence"] = evidence_ids(result.get("evidence", []))
            if result.get("status") == "FAIL":
                result.setdefault("reasonCategory", "PRODUCT")
                result.setdefault("reason", "migrated failure; classification needs review")
            elif result.get("status") == "ENV_UNAVAILABLE":
                result.setdefault("reasonCategory", "ENVIRONMENT")
            elif result.get("status") == "NOT_RUN":
                result.setdefault("reason", "not run in the migrated batch")

    execution_stage = migrated.get("stages", {}).get("execution", {})
    execution_cycles: list[dict[str, Any]] = []
    if old_results:
        statuses = {result.get("status") for result in old_results if isinstance(result, dict)}
        cycle_result = "FAIL" if "FAIL" in statuses else "ENV_UNAVAILABLE" if "ENV_UNAVAILABLE" in statuses else "PASS" if "PASS" in statuses else "NOT_RUN"
        cycle_status = "COMPLETED" if execution_stage.get("state") == "COMPLETED" else "PENDING"
        execution_cycles.append({
            "cycleId": "cycle-001", "type": "INITIAL", "status": cycle_status,
            "releaseBundleId": bundle_id,
            "environmentBindingId": environment.get("bindingId") or "migrated-unbound-environment",
            "environmentFingerprint": environment.get("observedFingerprint") or environment.get("fingerprint") or "migrated-unknown",
            "reason": "migrated initial execution batch", "startedAt": "migrated" if cycle_status == "COMPLETED" else None,
            "completedAt": "migrated" if cycle_status == "COMPLETED" else None,
            "result": cycle_result, "cleanupVerified": False,
            "testResults": old_results, "evidence": execution_stage.get("evidence", []), "missing": [],
        })
    migrated["executionCycles"] = execution_cycles

    report_stage = migrated.get("stages", {}).get("report", {})
    report_revisions: list[dict[str, Any]] = []
    lifecycle_state = "ACTIVE"
    if report_stage.get("state") == "COMPLETED":
        lifecycle_state = "REPORTED"
        report_revisions.append({
            "revision": 1, "createdAt": "migrated",
            "coveredCycles": [cycle["cycleId"] for cycle in execution_cycles if cycle["status"] == "COMPLETED"],
            "testRecordBatchId": f"migrated-{migrated['runId']}-batch-001",
            "testRecordEvidence": report_stage.get("evidence", []),
            "summary": report_stage.get("summary") or "migrated report",
        })
    migrated["lifecycle"] = {"state": lifecycle_state, "revision": 1, "reopenReason": "", "closedAt": None}
    migrated["reportRevisions"] = report_revisions
    migrated["testRecordIndexEvidence"] = report_stage.get("evidence", [None])[0] if report_revisions and report_stage.get("evidence") else None
    migrated["evidenceIndex"] = evidence_index
    migrated["schemaVersion"] = 2
    return migrated


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("validate", "status", "audit", "migrate"))
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--output", type=Path, help="new path for a migrated schemaVersion 2 manifest")
    args = parser.parse_args()
    try:
        data = load_manifest(args.manifest)
        if args.command == "migrate":
            if args.output is None:
                raise ManifestError("migrate requires --output")
            if args.output.exists():
                raise ManifestError(f"refusing to overwrite existing output: {args.output}")
            migrated = migrate_v1(data)
            errors = validate_manifest(migrated)
            if errors:
                print(json.dumps({"valid": False, "errors": errors}, indent=2))
                return 2
            args.output.write_text(json.dumps(migrated, indent=2) + "\n", encoding="utf-8")
            print(json.dumps({"valid": True, "output": str(args.output)}, indent=2))
            return 0
        errors = validate_manifest(data)
    except ManifestError as exc:
        print(json.dumps({"valid": False, "errors": [str(exc)]}, indent=2))
        return 2
    if errors:
        print(json.dumps({"valid": False, "errors": errors}, indent=2))
        return 2
    if args.command == "validate":
        output = {"valid": True, "errors": []}
    elif args.command == "status":
        output = {"valid": True, **progress(data)}
    else:
        output = audit_manifest(data, args.manifest)
    print(json.dumps(output, indent=2))
    return 0 if output.get("valid") else 2


if __name__ == "__main__":
    sys.exit(main())
