from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SCRIPT = Path(__file__).resolve().parent / "profile_manager.py"
SPEC = importlib.util.spec_from_file_location("profile_manager_test_target", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
PM = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PM
SPEC.loader.exec_module(PM)


class ProfileManagerTests(unittest.TestCase):
    def scaffold(self, root: Path, name: str = "candidate") -> Path:
        directory = root / name
        PM.scaffold(directory)
        return directory

    def test_public_templates_are_valid(self) -> None:
        assets = SCRIPT.parent.parent / "assets"
        environment = PM.load_json(assets / "environment-profile.template.json")
        recipe = PM.load_json(assets / "build-recipe.template.json")
        self.assertEqual([], PM.validate_environment(environment))
        self.assertEqual([], PM.validate_recipe(recipe))
        self.assertEqual(0, recipe["scopes"]["prepare-workspace"]["expectedArtifactCount"])
        self.assertEqual(0, recipe["scopes"]["cleanup-workspace"]["expectedArtifactCount"])

    def test_secret_bearing_fields_are_rejected(self) -> None:
        assets = SCRIPT.parent.parent / "assets"
        environment = PM.load_json(assets / "environment-profile.template.json")
        environment["nodes"][1]["password"] = "must-not-be-stored"
        errors = PM.validate_environment(environment)
        self.assertTrue(any("secret-bearing" in error for error in errors))

    def test_provider_hash_drift_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            candidate = self.scaffold(Path(temporary))
            provider = candidate / "providers" / "remote-build.sh"
            provider.write_text(provider.read_text(encoding="utf-8") + "\n# changed\n", encoding="utf-8")
            recipe = PM.require_valid_recipe(candidate / PM.RECIPE_FILE)
            with self.assertRaisesRegex(PM.ProfileError, "provider hash drift"):
                PM.require_provider(recipe, candidate / PM.RECIPE_FILE)

    def test_protected_material_is_kept_outside_project_profile(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project_profile = root / "project" / ".codex" / "profiles" / "build-client" / "example"
            codex_state = root / "user-codex"
            with mock.patch.dict("os.environ", {"CODEX_HOME": str(codex_state)}, clear=False):
                resolved = PM.resolve_protected_path(
                    project_profile,
                    "protected:profile/ssh-key",
                    binding_id="example-centos-build",
                    fingerprint="example-environment-v1",
                )
            self.assertTrue(resolved.is_relative_to(codex_state))
            self.assertFalse(resolved.is_relative_to(project_profile))

    def test_missing_profile_is_unconfigured(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(PM.ProfileError, "UNCONFIGURED"):
                PM.resolve_selection(registry_root=Path(temporary) / "registry")

    def test_private_save_and_discovery_copy_provider_outside_repo(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            candidate = self.scaffold(root)
            registry = root / "private-registry"
            result = PM.save_selection(
                environment_path=candidate / PM.ENVIRONMENT_FILE,
                recipe_path=candidate / PM.RECIPE_FILE,
                mode="PRIVATE",
                registry_root=registry,
            )
            self.assertEqual("PRIVATE", result["mode"])
            destination = registry / "example-centos-build"
            self.assertTrue((destination / PM.ENVIRONMENT_FILE).is_file())
            self.assertTrue((destination / "providers" / "remote-build.sh").is_file())
            selection = PM.resolve_selection(registry_root=registry)
            self.assertEqual("example-centos-build", selection.environment["bindingId"])
            self.assertEqual("PRIVATE", selection.mode)

    def test_multiple_profiles_require_explicit_choice(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            registry = root / "registry"
            first = self.scaffold(root, "first")
            PM.save_selection(
                environment_path=first / PM.ENVIRONMENT_FILE,
                recipe_path=first / PM.RECIPE_FILE,
                mode="PRIVATE",
                registry_root=registry,
            )
            second = self.scaffold(root, "second")
            environment_path = second / PM.ENVIRONMENT_FILE
            environment = PM.load_json(environment_path)
            environment["bindingId"] = "example-centos-build-2"
            environment["fingerprint"] = "example-environment-v2"
            environment_path.write_text(json.dumps(environment, indent=2) + "\n", encoding="utf-8")
            PM.save_selection(
                environment_path=environment_path,
                recipe_path=second / PM.RECIPE_FILE,
                mode="PRIVATE",
                registry_root=registry,
            )
            with self.assertRaisesRegex(PM.ProfileError, "CHOICE_REQUIRED"):
                PM.resolve_selection(registry_root=registry)
            selected = PM.resolve_selection(
                registry_root=registry, binding_id="example-centos-build-2"
            )
            self.assertEqual("example-environment-v2", selected.environment["fingerprint"])

    def test_fingerprint_drift_is_not_silently_replaced(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            registry = root / "registry"
            candidate = self.scaffold(root)
            environment_path = candidate / PM.ENVIRONMENT_FILE
            recipe_path = candidate / PM.RECIPE_FILE
            PM.save_selection(
                environment_path=environment_path,
                recipe_path=recipe_path,
                mode="PRIVATE",
                registry_root=registry,
            )
            environment = PM.load_json(environment_path)
            environment["fingerprint"] = "unexpected-replacement"
            environment_path.write_text(json.dumps(environment, indent=2) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(PM.ProfileError, "fingerprint changed"):
                PM.save_selection(
                    environment_path=environment_path,
                    recipe_path=recipe_path,
                    mode="PRIVATE",
                    registry_root=registry,
                    replace=True,
                )

    def test_project_persistence_requires_shareable_profiles(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            candidate = self.scaffold(root)
            environment_path = candidate / PM.ENVIRONMENT_FILE
            environment = PM.load_json(environment_path)
            environment["shareable"] = False
            environment_path.write_text(json.dumps(environment, indent=2) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(PM.ProfileError, "shareable"):
                PM.save_selection(
                    environment_path=environment_path,
                    recipe_path=candidate / PM.RECIPE_FILE,
                    mode="PROJECT",
                    project_root=root / "project",
                )

    def test_session_mode_does_not_persist(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            candidate = self.scaffold(root)
            result = PM.save_selection(
                environment_path=candidate / PM.ENVIRONMENT_FILE,
                recipe_path=candidate / PM.RECIPE_FILE,
                mode="SESSION",
            )
            self.assertFalse(result["persisted"])
            self.assertFalse((root / "profiles").exists())


if __name__ == "__main__":
    unittest.main()
