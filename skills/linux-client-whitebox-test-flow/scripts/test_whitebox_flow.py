#!/usr/bin/env python3

import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("whitebox_flow", HERE / "whitebox_flow.py")
FLOW = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(FLOW)
TEMPLATE = HERE.parent / "assets" / "whitebox-run.template.json"


def template():
    return json.loads(TEMPLATE.read_text(encoding="utf-8"))


def add_evidence(data, evidence_id, *, kind="COMMAND", ref=None, **extra):
    if any(item["id"] == evidence_id for item in data["evidenceIndex"]):
        return
    item = {"id": evidence_id, "kind": kind, "ref": ref or f"record:{evidence_id}", "encoding": "UTF-8"}
    item.update(extra)
    data["evidenceIndex"].append(item)


def verify_bindings(data):
    add_evidence(data, "ev-environment")
    add_evidence(data, "ev-bundle")
    data["environment"].update(
        state="VERIFIED", bindingId="linux-lab", profileRef="private:linux-lab",
        persistence="PRIVATE", fingerprint="lab-v1", observedFingerprint="lab-v1",
        nodeIds=["builder", "vm-secondary"], capabilities=["build", "test"],
        evidence=["ev-environment"],
    )
    data["releaseBundle"].update(
        state="VERIFIED", bundleId="bundle-001", bundleSha256="1" * 64,
        components=[
            {"name": "producer", "role": "producer", "gitCommit": "abc",
             "sourceManifestSha256": "2" * 64, "artifactSha256": "3" * 64},
            {"name": "consumer", "role": "consumer", "gitCommit": "def",
             "sourceManifestSha256": "4" * 64, "artifactSha256": "5" * 64},
        ],
        evidence=["ev-bundle"], reason="",
    )


def complete(data, stage, **extra):
    evidence_id = f"ev-stage-{stage}"
    add_evidence(data, evidence_id)
    data["stages"][stage].update(
        state="COMPLETED", summary=f"{stage} complete", evidence=[evidence_id], **extra,
    )


def approve(data, stage, decision="PROCEED"):
    data["approvals"][stage] = {"decision": decision, "timestamp": "2026-08-28T00:00:00Z"}


def add_pass_cycle(data, cycle_id="cycle-001", cycle_type="INITIAL", reason="initial suite"):
    evidence_id = f"ev-{cycle_id}"
    add_evidence(data, evidence_id)
    data["executionCycles"].append({
        "cycleId": cycle_id, "type": cycle_type, "status": "COMPLETED",
        "releaseBundleId": "bundle-001", "environmentBindingId": "linux-lab",
        "environmentFingerprint": "lab-v1", "reason": reason,
        "startedAt": "2026-08-28T00:00:00Z", "completedAt": "2026-08-28T00:01:00Z",
        "result": "PASS", "cleanupVerified": True, "missing": [],
        "testResults": [{
            "id": f"case-{cycle_id}", "layer": "system", "status": "PASS",
            "command": "run-suite", "evidence": [evidence_id],
        }],
        "evidence": [evidence_id],
    })


def reported_run():
    data = template()
    verify_bindings(data)
    for stage in ("intake", "discovery", "plan", "test_assets"):
        complete(data, stage)
        approve(data, stage)
    complete(data, "review", decision="PASS")
    approve(data, "review")
    complete(data, "build", result="PASS")
    approve(data, "build")
    add_pass_cycle(data)
    complete(data, "execution", result="PASS")
    approve(data, "execution")
    complete(data, "report")
    add_evidence(data, "ev-test-record")
    add_evidence(data, "ev-record-index", kind="RECORD_INDEX", ref="test-record-index.json", sha256="0" * 64)
    data["reportRevisions"] = [{
        "revision": 1, "createdAt": "2026-08-28T00:02:00Z",
        "coveredCycles": ["cycle-001"], "testRecordBatchId": "batch-001",
        "testRecordEvidence": ["ev-test-record"], "summary": "initial report",
    }]
    data["testRecordIndexEvidence"] = "ev-record-index"
    data["lifecycle"].update(state="REPORTED", revision=1)
    return data


class FlowTests(unittest.TestCase):
    def test_v2_template_is_valid_and_stops_for_profile(self):
        data = template()
        self.assertEqual([], FLOW.validate_manifest(data))
        status = FLOW.progress(data)
        self.assertEqual("environment_setup", status["currentStage"])
        self.assertTrue(status["stopForUserDecision"])

    def test_verified_environment_requires_release_bundle(self):
        data = template()
        verify_bindings(data)
        data["releaseBundle"].update(state="UNRESOLVED", bundleId=None, bundleSha256=None, components=[], evidence=[])
        self.assertEqual([], FLOW.validate_manifest(data))
        self.assertEqual("candidate_setup", FLOW.progress(data)["currentStage"])

    def test_verified_environment_and_bundle_allow_intake(self):
        data = template()
        verify_bindings(data)
        self.assertEqual([], FLOW.validate_manifest(data))
        self.assertEqual("intake", FLOW.progress(data)["currentStage"])

    def test_release_bundle_requires_every_component_identity(self):
        data = template()
        verify_bindings(data)
        data["releaseBundle"]["components"][1]["sourceManifestSha256"] = None
        data["releaseBundle"]["components"][1]["artifactSha256"] = None
        self.assertTrue(any("needs sourceManifestSha256 or artifactSha256" in error for error in FLOW.validate_manifest(data)))

    def test_checkpointed_stage_stops_for_decision(self):
        data = template()
        verify_bindings(data)
        complete(data, "intake")
        self.assertEqual([], FLOW.validate_manifest(data))
        self.assertTrue(FLOW.progress(data)["stopForUserDecision"])

    def test_continuous_authorization_advances_without_stage_prompt(self):
        data = template()
        verify_bindings(data)
        data["authorization"].update(
            mode="CONTINUOUS", grantId="grant-1", grantedAt="2026-08-28T00:00:00Z",
            scope=list(FLOW.STAGES), pauseOn=sorted(FLOW.MANDATORY_PAUSES),
        )
        complete(data, "intake")
        self.assertEqual([], FLOW.validate_manifest(data))
        status = FLOW.progress(data)
        self.assertEqual("discovery", status["currentStage"])
        self.assertFalse(status["stopForUserDecision"])

    def test_continuous_authorization_cannot_remove_mandatory_pause(self):
        data = template()
        verify_bindings(data)
        data["authorization"].update(
            mode="CONTINUOUS", grantId="grant-1", grantedAt="now",
            scope=list(FLOW.STAGES), pauseOn=["FAILURE"],
        )
        self.assertTrue(any("pauseOn is missing" in error for error in FLOW.validate_manifest(data)))

    def test_continuous_execution_stops_on_failed_cycle(self):
        data = template()
        verify_bindings(data)
        data["authorization"].update(
            mode="CONTINUOUS", grantId="grant-1", grantedAt="now",
            scope=list(FLOW.STAGES), pauseOn=sorted(FLOW.MANDATORY_PAUSES),
        )
        for stage in ("intake", "discovery", "plan", "test_assets"):
            complete(data, stage)
        complete(data, "review", decision="PASS")
        complete(data, "build", result="PASS")
        add_evidence(data, "ev-cycle-fail")
        data["executionCycles"] = [{
            "cycleId": "cycle-fail", "type": "INITIAL", "status": "COMPLETED",
            "releaseBundleId": "bundle-001", "environmentBindingId": "linux-lab",
            "environmentFingerprint": "lab-v1", "reason": "compatibility failure",
            "startedAt": "now", "completedAt": "later", "result": "FAIL",
            "cleanupVerified": True, "missing": [], "evidence": ["ev-cycle-fail"],
            "testResults": [{
                "id": "case-fail", "layer": "system", "status": "FAIL", "command": "run",
                "reason": "old consumer rejected value", "reasonCategory": "COMPATIBILITY",
                "evidence": ["ev-cycle-fail"],
            }],
        }]
        data["stages"]["execution"]["state"] = "IN_PROGRESS"
        self.assertEqual([], FLOW.validate_manifest(data))
        self.assertTrue(FLOW.progress(data)["stopForUserDecision"])

    def test_compatibility_scope_requires_all_four_combinations(self):
        data = template()
        verify_bindings(data)
        data["scope"]["compatibility"] = True
        data["compatibilityMatrix"] = [{
            "id": "old-new", "producer": "OLD", "consumer": "NEW",
            "status": "NOT_RUN", "evidence": [],
        }]
        self.assertTrue(any("OLD/OLD" in error for error in FLOW.validate_manifest(data)))
        data["compatibilityMatrix"] = [
            {"id": f"compat-{producer}-{consumer}", "producer": producer, "consumer": consumer,
             "status": "NOT_RUN", "evidence": []}
            for producer, consumer in sorted(FLOW.COMPATIBILITY_PAIRS)
        ]
        self.assertEqual([], FLOW.validate_manifest(data))

    def test_failure_requires_reason_category(self):
        data = template()
        verify_bindings(data)
        add_evidence(data, "ev-fail")
        data["executionCycles"] = [{
            "cycleId": "cycle-fail", "type": "INITIAL", "status": "COMPLETED",
            "releaseBundleId": "bundle-001", "environmentBindingId": "linux-lab",
            "environmentFingerprint": "lab-v1", "reason": "failure cycle",
            "startedAt": "now", "completedAt": "later", "result": "FAIL",
            "cleanupVerified": True, "missing": [], "evidence": ["ev-fail"],
            "testResults": [{"id": "case-fail", "layer": "system", "status": "FAIL",
                             "command": "run", "reason": "bad output", "evidence": ["ev-fail"]}],
        }]
        self.assertTrue(any("reasonCategory" in error for error in FLOW.validate_manifest(data)))

    def test_reported_run_is_valid(self):
        data = reported_run()
        self.assertEqual([], FLOW.validate_manifest(data))
        status = FLOW.progress(data)
        self.assertEqual("REPORTED", status["currentState"])
        self.assertTrue(status["stopForUserDecision"])

    def test_reopened_run_routes_to_supplemental_cycle_then_report(self):
        data = reported_run()
        data["lifecycle"].update(state="REOPENED", revision=2, reopenReason="secondary VM supplemental coverage")
        data["executionCycles"].append({
            "cycleId": "cycle-002", "type": "SUPPLEMENTAL", "status": "PENDING",
            "releaseBundleId": "bundle-001", "environmentBindingId": "linux-lab",
            "environmentFingerprint": "lab-v1", "reason": "secondary VM compatibility supplement",
            "startedAt": None, "completedAt": None, "result": "NOT_RUN",
            "cleanupVerified": False, "missing": [], "testResults": [], "evidence": [],
        })
        self.assertEqual([], FLOW.validate_manifest(data))
        self.assertEqual("execution", FLOW.progress(data)["currentStage"])
        data["executionCycles"].pop()
        add_pass_cycle(data, "cycle-002", "SUPPLEMENTAL", "secondary VM compatibility supplement")
        self.assertEqual([], FLOW.validate_manifest(data))
        self.assertEqual("report", FLOW.progress(data)["currentStage"])

    def test_second_report_revision_covers_supplemental_cycle(self):
        data = reported_run()
        data["lifecycle"].update(state="REOPENED", revision=2, reopenReason="supplemental")
        add_pass_cycle(data, "cycle-002", "SUPPLEMENTAL", "supplemental")
        add_evidence(data, "ev-test-record-2")
        data["reportRevisions"].append({
            "revision": 2, "createdAt": "2026-08-28T01:00:00Z",
            "coveredCycles": ["cycle-002"], "testRecordBatchId": "batch-002",
            "testRecordEvidence": ["ev-test-record-2"], "summary": "supplemental report",
        })
        data["lifecycle"].update(state="REPORTED", reopenReason="")
        self.assertEqual([], FLOW.validate_manifest(data))

    def test_historical_bundle_keeps_old_cycles_valid(self):
        data = reported_run()
        old_bundle = json.loads(json.dumps(data["releaseBundle"]))
        data["releaseBundleHistory"] = [old_bundle]
        add_evidence(data, "ev-bundle-002")
        data["releaseBundle"].update(
            bundleId="bundle-002", bundleSha256="6" * 64,
            components=[{"name": "producer", "role": "producer", "gitCommit": "new",
                         "sourceManifestSha256": "7" * 64, "artifactSha256": "8" * 64}],
            evidence=["ev-bundle-002"],
        )
        self.assertEqual([], FLOW.validate_manifest(data))
        data["lifecycle"].update(state="REOPENED", revision=2, reopenReason="new candidate")
        data["executionCycles"].append({
            "cycleId": "cycle-002", "type": "RETEST", "status": "PENDING",
            "releaseBundleId": "bundle-001", "environmentBindingId": "linux-lab",
            "environmentFingerprint": "lab-v1", "reason": "incorrect old binding",
            "startedAt": None, "completedAt": None, "result": "NOT_RUN",
            "cleanupVerified": False, "missing": [], "testResults": [], "evidence": [],
        })
        self.assertTrue(any("must match the current" in error for error in FLOW.validate_manifest(data)))

    def test_closed_run_requires_timestamp_and_has_terminal_status(self):
        data = reported_run()
        data["lifecycle"].update(state="CLOSED", revision=2, closedAt="2026-08-28T02:00:00Z")
        self.assertEqual([], FLOW.validate_manifest(data))
        self.assertEqual("CLOSED", FLOW.progress(data)["currentState"])
        data["executionCycles"][0]["cleanupVerified"] = False
        self.assertTrue(any("cleanup readback" in error for error in FLOW.validate_manifest(data)))

    def test_audit_checks_local_hash_and_cleanup(self):
        data = reported_run()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            evidence_path = root / "cycle.log"
            evidence_path.write_text("evidence\n", encoding="utf-8")
            digest = hashlib.sha256(evidence_path.read_bytes()).hexdigest()
            item = next(item for item in data["evidenceIndex"] if item["id"] == "ev-cycle-001")
            item.update(kind="LOCAL_FILE", ref="cycle.log", sha256=digest)
            record_index_path = root / "test-record-index.json"
            record_index = {
                "schemaVersion": 1, "runId": data["runId"],
                "requirementRef": data["target"]["requirementRef"],
                "reportRevisions": [
                    {"revision": revision["revision"], "testRecordBatchId": revision["testRecordBatchId"],
                     "coveredCycles": revision["coveredCycles"]}
                    for revision in data["reportRevisions"]
                ],
            }
            record_index_path.write_text(json.dumps(record_index), encoding="utf-8")
            record_item = next(item for item in data["evidenceIndex"] if item["id"] == "ev-record-index")
            record_item["sha256"] = hashlib.sha256(record_index_path.read_bytes()).hexdigest()
            manifest_path = root / "run.json"
            manifest_path.write_text(json.dumps(data), encoding="utf-8")
            audit = FLOW.audit_manifest(data, manifest_path)
            self.assertTrue(audit["valid"], audit)
            evidence_path.write_text("tampered\n", encoding="utf-8")
            self.assertFalse(FLOW.audit_manifest(data, manifest_path)["valid"])
            data["executionCycles"][0]["cleanupVerified"] = False
            self.assertTrue(any("cleanup" in error for error in FLOW.audit_manifest(data, manifest_path)["errors"]))

    def test_audit_detects_report_lag(self):
        data = reported_run()
        data["lifecycle"].update(state="REOPENED", revision=2, reopenReason="late cycle")
        add_pass_cycle(data, "cycle-002", "SUPPLEMENTAL", "late cycle")
        data["stages"]["report"]["state"] = "COMPLETED"
        audit = FLOW.audit_manifest(data, Path("run.json"))
        self.assertTrue(any("unreported cycles" in error for error in audit["errors"]))

    def test_audit_detects_manifest_behind_structured_test_record(self):
        data = reported_run()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            record_index_path = root / "test-record-index.json"
            record_index = {
                "schemaVersion": 1, "runId": data["runId"],
                "requirementRef": data["target"]["requirementRef"],
                "reportRevisions": [
                    {"revision": 1, "testRecordBatchId": "batch-001", "coveredCycles": ["cycle-001"]},
                    {"revision": 2, "testRecordBatchId": "batch-002", "coveredCycles": ["cycle-002"]},
                ],
            }
            record_index_path.write_text(json.dumps(record_index), encoding="utf-8")
            record_item = next(item for item in data["evidenceIndex"] if item["id"] == "ev-record-index")
            record_item["sha256"] = hashlib.sha256(record_index_path.read_bytes()).hexdigest()
            audit = FLOW.audit_manifest(data, root / "run.json")
            self.assertTrue(any("manifest is behind" in error for error in audit["errors"]))

    def test_migrate_v1_preserves_history_in_v2(self):
        old = {
            "schemaVersion": 1, "runId": "legacy-run",
            "target": {"repository": "repo", "gitRef": "main", "component": "client",
                       "changeType": "feature", "requirementRef": "req", "testRecordRef": "record"},
            "candidate": {"sourceManifestSha256": "a" * 64, "gitCommit": "abc"},
            "environment": {"state": "VERIFIED", "bindingId": "lab", "profileRef": "private:lab",
                            "persistence": "PRIVATE", "fingerprint": "fp", "observedFingerprint": "fp",
                            "capabilities": ["test"], "evidence": ["env.log"], "reason": ""},
            "scope": {"testLevels": ["system"]},
            "stages": {}, "approvals": {},
            "testResults": [{"id": "case-1", "layer": "system", "status": "PASS",
                             "command": "run", "evidence": ["case.log"]}],
        }
        for stage in FLOW.STAGES:
            old["stages"][stage] = {"state": "COMPLETED", "summary": f"{stage} done",
                                      "evidence": [f"{stage}.log"], "missing": []}
            if stage not in {"report"}:
                old["approvals"][stage] = {"decision": "PROCEED", "timestamp": "now"}
        old["stages"]["review"]["decision"] = "PASS"
        old["stages"]["build"]["result"] = "PASS"
        old["stages"]["execution"]["result"] = "PASS"
        migrated = FLOW.migrate_v1(old)
        self.assertEqual(2, migrated["schemaVersion"])
        self.assertEqual("REPORTED", migrated["lifecycle"]["state"])
        self.assertEqual(1, len(migrated["executionCycles"]))
        self.assertEqual([], FLOW.validate_manifest(migrated))

    def test_unknown_evidence_reference_is_rejected(self):
        data = template()
        verify_bindings(data)
        data["releaseBundle"]["evidence"] = ["missing-evidence"]
        self.assertTrue(any("unknown evidence ID" in error for error in FLOW.validate_manifest(data)))

    def test_remote_receipt_requires_recorded_validation_status(self):
        data = template()
        verify_bindings(data)
        add_evidence(data, "ev-remote", kind="REMOTE_RECEIPT", ref="receipt:remote", verifiedAt="now")
        self.assertTrue(any("validationStatus" in error for error in FLOW.validate_manifest(data)))
        remote = next(item for item in data["evidenceIndex"] if item["id"] == "ev-remote")
        remote["validationStatus"] = "VALID"
        self.assertEqual([], FLOW.validate_manifest(data))


if __name__ == "__main__":
    unittest.main()
