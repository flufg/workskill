#!/usr/bin/env python3

import importlib.util
import json
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


def complete(data, stage, **extra):
    data["stages"][stage].update(
        state="COMPLETED", summary=f"{stage} complete",
        evidence=[f"evidence/{stage}.json"], **extra,
    )


def approve(data, stage, decision="PROCEED"):
    data["approvals"][stage] = {"decision": decision, "timestamp": "2026-08-27T12:00:00Z"}


class FlowTests(unittest.TestCase):
    def test_unconfigured_template_is_valid_and_stops_for_profile(self):
        data = template()
        self.assertEqual([], FLOW.validate_manifest(data))
        status = FLOW.progress(data)
        self.assertEqual("environment_setup", status["currentStage"])
        self.assertTrue(status["stopForUserDecision"])

    def test_configured_environment_requires_binding_and_record(self):
        data = template()
        data["environment"].update(
            state="CONFIGURED", persistence="PRIVATE",
            profileRef="private:linux-vm", fingerprint="linux-vm-1",
            capabilities=["build", "test"], evidence=["profile:linux-vm"],
        )
        data["target"]["testRecordRef"] = ""
        errors = FLOW.validate_manifest(data)
        self.assertIn("environment.bindingId must be non-empty when state is CONFIGURED", errors)
        self.assertIn("target.testRecordRef must be non-empty", errors)

    def test_configured_environment_routes_to_preflight(self):
        data = template()
        data["environment"].update(
            state="CONFIGURED", bindingId="linux-vm", profileRef="private:linux-vm",
            persistence="PRIVATE", fingerprint="linux-vm-1",
            capabilities=["build", "test"], evidence=["profile:linux-vm"],
        )
        self.assertEqual([], FLOW.validate_manifest(data))
        status = FLOW.progress(data)
        self.assertEqual("environment_preflight", status["currentStage"])
        self.assertFalse(status["stopForUserDecision"])

    def test_verified_environment_allows_intake(self):
        data = template()
        data["environment"].update(
            state="VERIFIED", bindingId="linux-vm", profileRef="private:linux-vm",
            persistence="PRIVATE", fingerprint="linux-vm-1", observedFingerprint="linux-vm-1",
            capabilities=["build", "test"], evidence=["preflight:linux-vm"],
        )
        self.assertEqual([], FLOW.validate_manifest(data))
        self.assertEqual("intake", FLOW.progress(data)["currentStage"])

    def test_verified_environment_rejects_fingerprint_mismatch(self):
        data = template()
        data["environment"].update(
            state="VERIFIED", bindingId="linux-vm", profileRef="session:linux-vm",
            persistence="SESSION", fingerprint="expected", observedFingerprint="new-environment",
            capabilities=["build", "test"], evidence=["preflight:linux-vm"],
        )
        self.assertIn(
            "VERIFIED environment requires matching fingerprint and observedFingerprint",
            FLOW.validate_manifest(data),
        )

    def test_drifted_environment_stops_for_save_decision(self):
        data = template()
        data["environment"].update(
            state="DRIFTED", bindingId="linux-vm", profileRef="private:linux-vm",
            persistence="PRIVATE", fingerprint="expected", observedFingerprint="new-environment",
            reason="observed a new fingerprint",
        )
        self.assertEqual([], FLOW.validate_manifest(data))
        status = FLOW.progress(data)
        self.assertEqual("environment_setup", status["currentStage"])
        self.assertTrue(status["stopForUserDecision"])

    def verified(self, data):
        data["environment"].update(
            state="VERIFIED", bindingId="linux-vm", profileRef="private:linux-vm",
            persistence="PRIVATE", fingerprint="linux-vm-1", observedFingerprint="linux-vm-1",
            capabilities=["build", "test"], evidence=["preflight:linux-vm"],
        )

    def test_git_ref_rejects_filesystem_path(self):
        data = template()
        self.verified(data)
        data["target"]["gitRef"] = "/private/source/tree"
        self.assertIn("target.gitRef must be a Git ref, not a filesystem path", FLOW.validate_manifest(data))

    def test_completed_stage_stops_for_decision(self):
        data = template()
        self.verified(data)
        complete(data, "intake")
        self.assertTrue(FLOW.progress(data)["stopForUserDecision"])

    def test_explicit_approval_allows_next_stage(self):
        data = template()
        self.verified(data)
        complete(data, "intake")
        approve(data, "intake")
        self.assertEqual([], FLOW.validate_manifest(data))
        self.assertEqual("discovery", FLOW.progress(data)["currentStage"])

    def test_cannot_skip_stage_or_approval(self):
        data = template()
        self.verified(data)
        data["stages"]["discovery"]["state"] = "IN_PROGRESS"
        errors = FLOW.validate_manifest(data)
        self.assertTrue(any("before intake" in error for error in errors))
        self.assertTrue(any("PROCEED approval after intake" in error for error in errors))

    def test_build_requires_passing_review(self):
        data = template()
        self.verified(data)
        for stage in ("intake", "discovery", "plan", "test_assets"):
            complete(data, stage)
            approve(data, stage)
        complete(data, "review", decision="FAIL")
        approve(data, "review")
        data["stages"]["build"]["state"] = "IN_PROGRESS"
        self.assertIn("build cannot start until review decision is PASS", FLOW.validate_manifest(data))

    def test_execution_requires_successful_build(self):
        data = template()
        self.verified(data)
        for stage in ("intake", "discovery", "plan", "test_assets"):
            complete(data, stage)
            approve(data, stage)
        complete(data, "review", decision="PASS")
        approve(data, "review")
        complete(data, "build", result="FAIL")
        approve(data, "build")
        data["stages"]["execution"]["state"] = "IN_PROGRESS"
        self.assertIn("execution cannot start until build result is PASS", FLOW.validate_manifest(data))

    def test_passed_test_needs_command_and_evidence(self):
        data = template()
        self.verified(data)
        data["testResults"] = [{"id": "unit-1", "layer": "unit", "status": "PASS"}]
        errors = FLOW.validate_manifest(data)
        self.assertTrue(any("needs command" in error for error in errors))
        self.assertTrue(any("needs evidence" in error for error in errors))

    def test_only_one_active_stage(self):
        data = template()
        self.verified(data)
        data["stages"]["intake"]["state"] = "IN_PROGRESS"
        data["stages"]["discovery"].update(state="BLOCKED", summary="missing source", missing=["source manifest"])
        self.assertTrue(any("at most one stage" in error for error in FLOW.validate_manifest(data)))


if __name__ == "__main__":
    unittest.main()
