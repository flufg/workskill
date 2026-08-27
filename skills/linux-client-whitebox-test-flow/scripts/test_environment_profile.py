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
    def test_template_is_valid(self):
        self.assertEqual([], PROFILE.validate_profile(template()))

    def test_secret_bearing_profile_is_rejected(self):
        data = template()
        data["containsSecrets"] = True
        self.assertIn(
            "containsSecrets must be false; store only protected credential references",
            PROFILE.validate_profile(data),
        )

    def test_preflight_and_cleanup_are_required(self):
        data = template()
        data["commands"]["preflight"] = ""
        data["commands"]["cleanup"] = ""
        errors = PROFILE.validate_profile(data)
        self.assertIn("commands.preflight must be non-empty", errors)
        self.assertIn("commands.cleanup must be non-empty", errors)


if __name__ == "__main__":
    unittest.main()
