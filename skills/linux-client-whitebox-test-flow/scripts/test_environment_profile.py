#!/usr/bin/env python3

import importlib.util
import json
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("environment_profile", HERE / "environment_profile.py")
PROFILE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(PROFILE)
TEMPLATE = HERE.parent / "assets" / "environment-profile.template.json"


def template():
    return json.loads(TEMPLATE.read_text(encoding="utf-8"))


class EnvironmentProfileTests(unittest.TestCase):
    def test_v2_multi_node_template_is_valid(self):
        self.assertEqual([], PROFILE.validate_profile(template()))

    def test_secret_bearing_profile_is_rejected(self):
        data = template()
        data["containsSecrets"] = True
        data["nodes"][0]["password"] = "plain-text"
        errors = PROFILE.validate_profile(data)
        self.assertTrue(any("containsSecrets" in error for error in errors))
        self.assertTrue(any("secret-bearing field" in error for error in errors))

    def test_each_node_has_scoped_protected_credentials(self):
        data = template()
        data["nodes"].append({
            "nodeId": "vm-secondary", "roles": ["test"], "platform": "distro-b",
            "fingerprint": "vm-secondary-v1", "accessRef": "protected:ssh-secondary",
            "privilegeRef": "protected:sudo-secondary",
            "credentialRefs": {"redis": "protected:redis-secondary"},
            "capabilities": ["test", "redis"],
            "commands": {"test": "test-provider", "preflight": "preflight-secondary", "cleanup": "cleanup-secondary"},
        })
        self.assertEqual([], PROFILE.validate_profile(data))
        data["nodes"][1]["credentialRefs"]["redis"] = "raw-password"
        self.assertTrue(any("protected/provider/session" in error for error in PROFILE.validate_profile(data)))

    def test_role_specific_commands_are_required(self):
        data = template()
        data["nodes"][0]["commands"]["build"] = ""
        data["nodes"][0]["commands"]["cleanup"] = ""
        errors = PROFILE.validate_profile(data)
        self.assertTrue(any("commands.build" in error for error in errors))
        self.assertTrue(any("commands.cleanup" in error for error in errors))

    def test_duplicate_node_ids_are_rejected(self):
        data = template()
        data["nodes"].append(json.loads(json.dumps(data["nodes"][0])))
        self.assertTrue(any("duplicate nodeId" in error for error in PROFILE.validate_profile(data)))


if __name__ == "__main__":
    unittest.main()
