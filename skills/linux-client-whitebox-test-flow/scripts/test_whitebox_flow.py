#!/usr/bin/env python3

import copy
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
    def test_template_is_valid_and_starts_at_intake(self):
        data = template()
        self.assertEqual([], FLOW.validate_manifest(data))
        self.assertEqual("intake", FLOW.progress(data)["currentStage"])

    def test_environment_binding_and_record_are_required(self):
        data = template()
        data["environment"]["bindingId"] = ""
        data["target"]["testRecordRef"] = ""
        errors = FLOW.validate_manifest(data)
        self.assertIn("environment.bindingId must be non-empty", errors)
        self.assertIn("target.testRecordRef must be non-empty", errors)

    def test_git_ref_rejects_filesystem_path(self):
        data = template()
        data["target"]["gitRef"] = "/private/source/tree"
        self.assertIn("target.gitRef must be a Git ref, not a filesystem path", FLOW.validate_manifest(data))

    def test_completed_stage_stops_for_decision(self):
        data = template()
        complete(data, "intake")
        self.assertTrue(FLOW.progress(data)["stopForUserDecision"])

    def test_explicit_approval_allows_next_stage(self):
        data = template()
        complete(data, "intake")
        approve(data, "intake")
        self.assertEqual([], FLOW.validate_manifest(data))
        self.assertEqual("discovery", FLOW.progress(data)["currentStage"])

    def test_cannot_skip_stage_or_approval(self):
        data = template()
        data["stages"]["discovery"]["state"] = "IN_PROGRESS"
        errors = FLOW.validate_manifest(data)
        self.assertTrue(any("before intake" in error for error in errors))
        self.assertTrue(any("PROCEED approval after intake" in error for error in errors))

    def test_build_requires_passing_review(self):
        data = template()
        for stage in ("intake", "discovery", "plan", "test_assets"):
            complete(data, stage)
            approve(data, stage)
        complete(data, "review", decision="FAIL")
        approve(data, "review")
        data["stages"]["build"]["state"] = "IN_PROGRESS"
        self.assertIn("build cannot start until review decision is PASS", FLOW.validate_manifest(data))

    def test_execution_requires_successful_build(self):
        data = template()
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
        data["testResults"] = [{"id": "unit-1", "layer": "unit", "status": "PASS"}]
        errors = FLOW.validate_manifest(data)
        self.assertTrue(any("needs command" in error for error in errors))
        self.assertTrue(any("needs evidence" in error for error in errors))

    def test_only_one_active_stage(self):
        data = template()
        data["stages"]["intake"]["state"] = "IN_PROGRESS"
        data["stages"]["discovery"].update(state="BLOCKED", summary="missing source", missing=["source manifest"])
        self.assertTrue(any("at most one stage" in error for error in FLOW.validate_manifest(data)))


if __name__ == "__main__":
    unittest.main()
